"""Orchestration: routes utterances, drives turns, speaks results.

State model:
- Mic is always segmenting (except while TTS plays, to avoid feedback).
- An utterance reaches Claude when it starts with a wake word, OR the answer
  window is open (right after Claude spoke), OR a permission/answer future is
  pending.
- Messages arriving while a turn runs are buffered and sent afterwards.
"""

from __future__ import annotations

import asyncio
import sys
import time

from .config import Config
from .session import ClaudeSession, TurnResult
from .tts import Speaker
from .wake import Command, match_wake, parse_command, parse_yes_no


class App:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.speaker = Speaker(config.voice, config.speech_rate, config.mute)
        self.session = ClaudeSession(config, self._ask_permission)
        self.mic = None  # set in voice mode
        self._messages: asyncio.Queue[str] = asyncio.Queue()
        self._answer_future: asyncio.Future[str] | None = None
        self._window_until: float = 0.0

    # ---------- speaking (mutes mic against feedback) ----------

    async def speak(self, text: str, sanitize: bool = True) -> None:
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

    @property
    def _window_open(self) -> bool:
        return time.monotonic() < self._window_until

    # ---------- input routing (voice and typed share this) ----------

    async def handle_utterance(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        # 1. Someone is waiting for an answer (permission dialog etc.)
        if self._answer_future and not self._answer_future.done():
            print(f"\033[33m🎤 (Antwort) {text}\033[0m", flush=True)
            self._answer_future.set_result(text)
            return
        # 2. Wake word or open answer window
        content = match_wake(text, self.config.wake_words)
        if content is None:
            if self._window_open:
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
            self.speaker.stop()
            if self.session.working:
                await self.session.interrupt()
                await self.speak("Okay, gestoppt. Wie machen wir weiter?", sanitize=False)
                self._open_window()
            return
        if routed.command is Command.STATUS:
            await self.speak(self.session.status_de, sanitize=False)
            return
        if self.session.working:
            await self.speaker.earcon("ack")
            print("\033[2m  (gepuffert bis zum Turn-Ende)\033[0m", flush=True)
        self._messages.put_nowait(routed.text)

    # ---------- permission dialog (called from inside a running turn) ----------

    async def _ask_permission(self, spoken_summary: str) -> bool:
        await self.speaker.earcon("attention")
        question = f"Claude möchte {spoken_summary}. Ja oder Nein?"
        for _attempt in range(2):
            await self.speak(question, sanitize=False)
            answer = await self._await_answer(self.config.permission_timeout_s)
            if answer is None:
                await self.speak("Keine Antwort, ich lehne ab.", sanitize=False)
                return False
            decision = parse_yes_no(answer)
            if decision is not None:
                await self.speak("Okay." if decision else "Abgelehnt.", sanitize=False)
                return decision
            question = "Bitte antworte mit Ja oder Nein."
        return False

    async def _await_answer(self, timeout: float) -> str | None:
        self._answer_future = asyncio.get_running_loop().create_future()
        try:
            return await asyncio.wait_for(self._answer_future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._answer_future = None

    # ---------- turn execution ----------

    async def _turn_worker(self) -> None:
        while True:
            message = await self._messages.get()
            try:
                result = await self.session.send(message)
            except Exception as exc:  # noqa: BLE001 — must not kill the loop while driving
                print(f"\033[31mFehler: {exc}\033[0m", flush=True)
                await self.speaker.earcon("error")
                await self.speak(
                    "Da ist etwas schiefgegangen. Sag es nochmal, wenn ich es "
                    "erneut versuchen soll.",
                    sanitize=False,
                )
                self._open_window()
                continue
            await self._speak_result(result)

    async def _speak_result(self, result: TurnResult) -> None:
        if result.is_error:
            await self.speaker.earcon("error")
        if result.text:
            await self.speak(result.text)
        else:
            await self.speak("Fertig, aber ohne Antworttext.", sanitize=False)
        print(f"\033[2m  (Turn: {result.elapsed_s:.0f}s)\033[0m", flush=True)
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
        stdin_task = asyncio.create_task(self._stdin_barge_in())
        await self.speak("Claude to go ist bereit.", sanitize=False)
        print("Sag »Claude …« — Enter stoppt die Sprachausgabe, Ctrl+C beendet.", flush=True)
        try:
            while True:
                audio = await utterances.get()
                text = await transcriber.transcribe(audio)
                if text:
                    await self.handle_utterance(text)
        finally:
            worker.cancel()
            stdin_task.cancel()
            self.mic.stop()
            await self.session.stop()

    async def _stdin_barge_in(self) -> None:
        """Enter = stop TTS; 'q' + Enter = quit."""
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if line == "":  # EOF
                return
            if line.strip().lower() == "q":
                raise KeyboardInterrupt
            self.speaker.stop()

    async def run_typed(self) -> None:
        await self.session.start()
        worker = asyncio.create_task(self._turn_worker())
        await self.speak("Claude to go, getippter Modus.", sanitize=False)
        print("Tippen und Enter. Kommandos: stop, status, q.", flush=True)
        loop = asyncio.get_running_loop()
        try:
            while True:
                line = (await loop.run_in_executor(None, sys.stdin.readline))
                if line == "":
                    break
                line = line.strip()
                if not line:
                    self.speaker.stop()
                    continue
                if line.lower() == "q":
                    break
                # typed input is always addressed to Claude — no wake word
                if self._answer_future and not self._answer_future.done():
                    self._answer_future.set_result(line)
                    continue
                await self.handle_typed(line)
        finally:
            worker.cancel()
            await self.session.stop()

    async def handle_typed(self, line: str) -> None:
        routed = parse_command(line)
        if routed.command is Command.STOP:
            self.speaker.stop()
            if self.session.working:
                await self.session.interrupt()
                await self.speak("Okay, gestoppt.", sanitize=False)
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
