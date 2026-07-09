"""Orchestration: routes utterances, drives turns, speaks results.

State model:
- Mic is always segmenting (except while TTS plays, to avoid feedback).
- An utterance reaches Claude when it starts with a wake word, OR the answer
  window is open (right after Claude spoke), OR a permission answer is pending.
- Permission answers must be a clear, short yes/no; anything else is either a
  new wake-word command or ignored — ambient speech must never grant actions.
- Messages arriving while a turn runs are buffered and sent afterwards.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time

from .config import Config
from .session import ClaudeSession, TurnResult
from .tts import Speaker
from .wake import Command, match_wake, parse_command, parse_yes_no


class App:
    def __init__(self, config: Config, interactive: bool = True) -> None:
        self.config = config
        self.interactive = interactive
        self.speaker = Speaker(config.voice, config.speech_rate, config.mute)
        self.session = ClaudeSession(config, self._ask_permission)
        self.mic = None  # set in voice mode
        self._messages: asyncio.Queue[str] = asyncio.Queue()
        self._answer_future: asyncio.Future[str] | None = None
        self._answer_started_at: float = 0.0
        self._window_until: float = 0.0
        self._interrupted_turn = False
        self._speak_lock = asyncio.Lock()       # serializes mute/say/unmute brackets
        self._permission_lock = asyncio.Lock()  # one spoken permission dialog at a time

    # ---------- speaking (mutes mic against feedback) ----------

    async def speak(self, text: str, sanitize: bool = True) -> None:
        async with self._speak_lock:
            if self.mic:
                self.mic.muted = True
            try:
                await self.speaker.say(text, sanitize=sanitize)
            finally:
                if self.mic:
                    await asyncio.sleep(0.3)
                    self.mic.muted = False

    def _open_window(self) -> None:
        self._window_until = time.monotonic() + self.config.answer_window_s

    # ---------- input routing (voice and typed share this) ----------

    async def handle_utterance(self, text: str, captured_at: float | None = None) -> None:
        text = text.strip()
        if not text:
            return
        if captured_at is None:
            captured_at = time.monotonic()
        wake_content = match_wake(text, self.config.wake_words)

        # 1. A permission dialog is waiting. Only utterances spoken AFTER the
        # question started count — a command still in the STT pipeline from
        # before must not be swallowed as an answer.
        future = self._answer_future
        if future and not future.done() and captured_at >= self._answer_started_at:
            candidate = wake_content if wake_content else text
            if parse_command(candidate).command is Command.STOP:
                print(f"\033[33m🎤 (Stopp während Freigabe) {text}\033[0m", flush=True)
                future.set_result("nein")
                await self._do_stop()
                return
            if parse_yes_no(candidate) is not None:
                print(f"\033[33m🎤 (Antwort) {candidate}\033[0m", flush=True)
                future.set_result(candidate)
                return
            if wake_content is None:
                print(f"\033[2m🎤 (ignoriert, keine klare Antwort) {text}\033[0m", flush=True)
                return
            # wake-addressed but not an answer: fall through as a new command

        # 2. Wake word or open answer window
        content = wake_content
        if content is None:
            if captured_at < self._window_until:
                content = text
            else:
                print(f"\033[2m🎤 (ignoriert) {text}\033[0m", flush=True)
                return
        if not content:
            # bare "Claude" — open a short window and confirm we listen
            self._open_window()
            await self.speaker.earcon("listen")
            return
        print(f"\033[33m🎤 {content}\033[0m", flush=True)
        self._window_until = 0.0
        routed = parse_command(content)
        if routed.command is Command.STOP:
            await self._do_stop()
            return
        if routed.command is Command.STATUS:
            await self.speak(self.session.status_de, sanitize=False)
            return
        if self.session.working:
            await self.speaker.earcon("ack")
            print("\033[2m  (gepuffert bis zum Turn-Ende)\033[0m", flush=True)
        self._messages.put_nowait(routed.text)

    async def _do_stop(self) -> None:
        self.speaker.stop()
        if self.session.working:
            self._interrupted_turn = True
            await self.session.interrupt()
            await self.speak("Okay, gestoppt. Wie machen wir weiter?", sanitize=False)
            self._open_window()

    # ---------- permission dialog (called from inside a running turn) ----------

    async def _ask_permission(self, spoken_summary: str) -> bool:
        if not self.interactive:
            print(f"\033[31m(auto-abgelehnt, kein Dialog möglich: {spoken_summary})\033[0m", flush=True)
            return False
        # The SDK spawns each permission request as its own task; without this
        # lock two questions would fight over one answer slot and the driver's
        # "Ja" could approve the wrong action.
        async with self._permission_lock:
            await self.speaker.earcon("attention")
            question = f"Claude möchte {spoken_summary}. Ja oder Nein?"
            for _attempt in range(2):
                answer = await self._ask_and_await(question, self.config.permission_timeout_s)
                if answer is None:
                    await self.speak("Keine Antwort, ich lehne ab.", sanitize=False)
                    return False
                decision = parse_yes_no(answer)
                if decision is not None:
                    await self.speak("Okay." if decision else "Abgelehnt.", sanitize=False)
                    return decision
                question = "Bitte antworte mit Ja oder Nein."
            await self.speak("Das war unklar — ich lehne sicherheitshalber ab.", sanitize=False)
            return False

    async def _ask_and_await(self, question: str, timeout: float) -> str | None:
        # Future exists BEFORE the question plays: a fast answer right after
        # the mic unmutes must land in the dialog, not in the message queue.
        self._answer_future = asyncio.get_running_loop().create_future()
        self._answer_started_at = time.monotonic()
        try:
            await self.speak(question, sanitize=False)
            return await asyncio.wait_for(self._answer_future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._answer_future = None

    # ---------- turn execution ----------

    async def _turn_worker(self) -> None:
        while True:
            message = await self._messages.get()
            self._interrupted_turn = False
            try:
                await self.speak("Ok.", sanitize=False)
                result = await self.session.send(message)
                if self._interrupted_turn:
                    continue  # stale result of an aborted turn — stay silent
                await self._speak_result(result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — must not kill the loop while driving
                print(f"\033[31mFehler: {exc}\033[0m", flush=True)
                await self.speaker.earcon("error")
                await self._recover_session()

    async def _recover_session(self) -> None:
        try:
            await self.session.reconnect()
            await self.speak(
                "Da ist etwas schiefgegangen, ich habe die Verbindung neu "
                "aufgebaut. Sag es bitte nochmal.",
                sanitize=False,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"\033[31mReconnect fehlgeschlagen: {exc}\033[0m", flush=True)
            await self.speak(
                "Ich bekomme gerade keine Verbindung zu Claude. Ich versuche "
                "es beim nächsten Auftrag erneut.",
                sanitize=False,
            )
        self._open_window()

    async def _speak_result(self, result: TurnResult) -> None:
        if result.is_error:
            await self.speaker.earcon("error")
        if result.text:
            await self.speak(result.text)
        else:
            await self.speak("Fertig, aber ohne Antworttext.", sanitize=False)
        print(f"\033[2m  (Turn: {result.elapsed_s:.0f}s)\033[0m", flush=True)
        if self._messages.empty():
            self._open_window()
            await self.speaker.earcon("listen")

    # ---------- modes ----------

    async def run_voice(self) -> None:
        from .audio import MicListener
        from .stt import Transcriber

        print("Lade Spracherkennung …", flush=True)
        transcriber = Transcriber(self.config.whisper_model, self.config.stt_language)
        utterances: asyncio.Queue = asyncio.Queue()
        self.mic = MicListener(
            device_substring=self.config.mic_device,
            sample_rate=self.config.sample_rate,
            vad_aggressiveness=self.config.vad_aggressiveness,
            min_s=self.config.utterance_min_s,
            max_s=self.config.utterance_max_s,
            silence_end_ms=self.config.silence_end_ms,
            loop=asyncio.get_running_loop(),
            out_queue=utterances,
        )
        await self.session.start()
        self.mic.start()
        worker = asyncio.create_task(self._turn_worker())
        stdin_queue = _stdin_line_queue()
        stdin_task = asyncio.create_task(self._stdin_barge_in(stdin_queue))
        await self.speak("Claude to go ist bereit.", sanitize=False)
        print("Sag »Claude …« — Enter stoppt die Sprachausgabe, q beendet.", flush=True)
        try:
            while True:
                captured_at, audio = await utterances.get()
                text = await transcriber.transcribe(audio)
                if text:
                    await self.handle_utterance(text, captured_at=captured_at)
        finally:
            worker.cancel()
            stdin_task.cancel()
            self.mic.stop()
            await self.session.stop()

    async def _stdin_barge_in(self, lines: asyncio.Queue) -> None:
        """Enter = stop TTS; 'q' + Enter = quit."""
        while True:
            line = await lines.get()
            if line is None:  # EOF
                return
            if line.strip().lower() == "q":
                raise KeyboardInterrupt
            self.speaker.stop()

    async def run_typed(self) -> None:
        await self.session.start()
        worker = asyncio.create_task(self._turn_worker())
        await self.speak("Claude to go, getippter Modus.", sanitize=False)
        print("Tippen und Enter. Kommandos: stop, status, q.", flush=True)
        lines = _stdin_line_queue()
        try:
            while True:
                line = await lines.get()
                if line is None:
                    break
                line = line.strip()
                if not line:
                    self.speaker.stop()
                    continue
                if line.lower() == "q":
                    break
                # typed input is always addressed to Claude — no wake word
                future = self._answer_future
                if future and not future.done():
                    future.set_result(line)
                    continue
                await self.handle_typed(line)
        finally:
            worker.cancel()
            await self.session.stop()

    async def handle_typed(self, line: str) -> None:
        routed = parse_command(line)
        if routed.command is Command.STOP:
            await self._do_stop()
            return
        if routed.command is Command.STATUS:
            await self.speak(self.session.status_de, sanitize=False)
            return
        self._messages.put_nowait(line)

    async def run_send_once(self, text: str) -> None:
        await self.session.start()
        try:
            result = await self.session.send(text)
            print(result.text)
            await self.speak(result.text)
        finally:
            await self.session.stop()


def _stdin_line_queue() -> asyncio.Queue:
    """Read stdin on a daemon thread so Ctrl+C shutdown never blocks on a
    parked readline (the default executor would join it forever)."""
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _reader() -> None:
        while True:
            line = sys.stdin.readline()
            loop.call_soon_threadsafe(queue.put_nowait, line if line else None)
            if not line:
                return

    threading.Thread(target=_reader, daemon=True).start()
    return queue
