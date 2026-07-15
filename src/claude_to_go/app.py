"""Orchestration: routes utterances, drives turns, speaks results.

State model:
- Mic is always segmenting — even during TTS. Utterances captured while the
  assistant speaks pass a STOP-ONLY gate (voice barge-in): stop words abort
  speech/turn, everything else is discarded (echo protection).
- An utterance reaches Claude when it starts with a wake word, OR the answer
  window is open (right after Claude spoke), OR a permission answer is pending.
- Permission answers must be a clear, short, CONFIDENT yes/no; "wiederhole"
  repeats the question, "details" reads the raw command.
- A near-miss (spoken shortly after the window closed) triggers a friendly
  "Meintest du mich?" instead of silent discard.
- Messages arriving while a turn runs are injected into the running turn.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .config import Config
from .i18n import get_strings
from .logbook import Logbook
from .session import ClaudeSession, TurnResult
from .tts import Speaker
from .wake import (
    Command,
    match_wake,
    parse_command,
    parse_permission_extra,
    parse_yes_no,
)

EventSink = Callable[[str, dict], None]


class App:
    def __init__(self, config: Config, interactive: bool = True) -> None:
        self.config = config
        self.interactive = interactive
        self.strings = get_strings(config.language)
        self.speaker = Speaker(
            config.voice, config.speech_rate, config.mute,
            locale=self.strings.voice_locale, fallback=self.strings.fallback_voice,
        )
        self.session = ClaudeSession(
            config, self._ask_permission, on_interjection_reply=self._on_interjection_reply
        )
        self.logbook = Logbook(config.log_dir)
        self.mic = None  # set in voice mode
        self.event_sink: EventSink | None = None  # phone UI updates
        self._messages: asyncio.Queue[str] = asyncio.Queue()
        self._answer_future: asyncio.Future[str] | None = None
        self._answer_started_at: float = 0.0
        self._window_until: float = 0.0
        self._window_timer: asyncio.Task | None = None
        self._grace_task: asyncio.Task | None = None
        self._interrupted_turn = False
        self._last_interim_spoken = ""
        self._tts_intervals: deque[tuple[float, float]] = deque(maxlen=8)
        self._current_tts_start: float | None = None
        self.pending_permission: dict | None = None  # phone reconnect resync
        self._speak_lock = asyncio.Lock()       # serializes TTS playback
        self._permission_lock = asyncio.Lock()  # one spoken dialog at a time

    # ---------- events to the phone UI (best-effort) ----------

    def emit(self, kind: str, **fields) -> None:
        if self.event_sink is not None:
            try:
                self.event_sink(kind, fields)
            except Exception:  # noqa: BLE001 — UI must never break the loop  # nosec B110
                pass

    # ---------- speaking ----------

    async def speak(self, text: str, sanitize: bool = True) -> None:
        async with self._speak_lock:
            start = time.monotonic()
            self._current_tts_start = start
            self.emit("state", value="speaking")
            self.emit("assistant", text=text)
            try:
                await self.speaker.say(text, sanitize=sanitize)
            finally:
                self._current_tts_start = None
                self._tts_intervals.append((start - 0.2, time.monotonic() + 0.5))
                self.emit("state", value="working" if self.session.working else "idle")

    def _in_tts(self, started_at: float, ended_at: float) -> bool:
        """Echo check by OVERLAP: an echo necessarily STARTS during playback.
        Comparing only the emission timestamp misses trailing echoes — the
        segmenter stamps ~0.8s (silence tail) after the last voiced frame."""
        if self._current_tts_start is not None and ended_at >= self._current_tts_start:
            return True
        return any(
            started_at <= iv_end and ended_at >= iv_start
            for iv_start, iv_end in self._tts_intervals
        )

    def _open_window(self) -> None:
        self._window_until = time.monotonic() + self.config.answer_window_s
        self.emit("window", open=True, seconds=self.config.answer_window_s)
        if self._window_timer is not None:
            self._window_timer.cancel()
        self._window_timer = asyncio.create_task(self._window_watch(self._window_until))

    def _close_window(self) -> None:
        self._window_until = 0.0
        if self._window_timer is not None:
            self._window_timer.cancel()
            self._window_timer = None
        self.emit("window", open=False)

    async def _window_watch(self, deadline: float) -> None:
        """Soft earcon when the answer window expires unused — silence reads
        as 'still listening' and the driver talks into the void otherwise."""
        try:
            await asyncio.sleep(max(0.0, deadline - time.monotonic()))
        except asyncio.CancelledError:
            return
        if self._window_until == deadline:
            self.emit("window", open=False)
            await self.speaker.earcon("window_close")

    # ---------- input routing (voice, typed, and phone buttons share this) ----------

    async def handle_utterance(
        self,
        text: str,
        captured_at: float | None = None,
        captured_end: float | None = None,
        usable: bool = True,
        confident: bool = True,
        from_button: bool = False,
    ) -> None:
        """`captured_at`/`captured_end` bracket the spoken utterance;
        `from_button` marks physical touch input, which can never be echo."""
        text = text.strip()
        if not text:
            return
        now = time.monotonic()
        if captured_at is None:
            captured_at = now
        if captured_end is None:
            captured_end = captured_at

        # 1. Voice barge-in gate: while the assistant speaks, ONLY stop words
        # act; everything else is (potential) echo and gets dropped.
        if not from_button and self._in_tts(captured_at, captured_end):
            wake_content = match_wake(text, self.strings.wake_words)
            candidate = wake_content if wake_content else text
            if parse_command(candidate, self.strings).command is Command.STOP and (
                wake_content is not None or len(candidate.split()) <= 2
            ):
                print(f"\033[33m🎤 (Barge-in) {text}\033[0m", flush=True)
                self.logbook.log("barge_in", text=text)
                await self._do_stop()
            else:
                print(f"\033[2m🎤 (während TTS verworfen) {text}\033[0m", flush=True)
                self.logbook.log("dropped_tts_echo", text=text)
            return

        if not usable:
            print(f"\033[2m🎤 (unsicher, verworfen) {text}\033[0m", flush=True)
            self.logbook.log("dropped_low_confidence", text=text)
            return

        wake_content = match_wake(text, self.strings.wake_words)

        # 2. A permission dialog is waiting. Only confident utterances spoken
        # AFTER the question started count.
        future = self._answer_future
        if future and not future.done() and captured_at >= self._answer_started_at:
            candidate = wake_content if wake_content else text
            if parse_command(candidate, self.strings).command is Command.STOP:
                print(f"\033[33m🎤 (Stopp während Freigabe) {text}\033[0m", flush=True)
                self.logbook.log("permission_stop", text=text)
                future.set_result("nein")
                await self._do_stop()
                return
            is_answer = parse_yes_no(candidate, self.strings) is not None or parse_permission_extra(candidate, self.strings) is not None
            if is_answer and confident:
                print(f"\033[33m🎤 (Antwort) {candidate}\033[0m", flush=True)
                future.set_result(candidate)
                return
            if is_answer and not confident:
                print(f"\033[2m🎤 (Antwort zu unsicher, ignoriert) {text}\033[0m", flush=True)
                self.logbook.log("dropped_unconfident_answer", text=text)
                return
            if wake_content is None:
                print(f"\033[2m🎤 (ignoriert, keine klare Antwort) {text}\033[0m", flush=True)
                return
            # wake-addressed but not an answer: fall through as a new command

        # 3. Wake word, open answer window, or near-miss grace
        content = wake_content
        if content is None:
            if captured_at < self._window_until:
                content = text
            elif (
                self._window_until > 0
                and captured_at < self._window_until + self.config.window_grace_s
                and confident
                and len(text.split()) >= 3
            ):
                # Off the consumer task: the dialog must not block the very
                # loop that transcribes the driver's "Ja".
                if self._grace_task is None or self._grace_task.done():
                    self._grace_task = asyncio.create_task(self._confirm_meant_me(text))
                return
            else:
                print(f"\033[2m🎤 (ignoriert) {text}\033[0m", flush=True)
                self.logbook.log("ignored", text=text)
                return
        if not content:
            # bare "Claude" — open a short window and confirm we listen
            self._open_window()
            await self.speaker.earcon("listen")
            return
        await self._dispatch(content)

    async def _dispatch(self, content: str) -> None:
        print(f"\033[33m🎤 {content}\033[0m", flush=True)
        self.emit("user", text=content)
        self._close_window()
        routed = parse_command(content, self.strings)
        self.logbook.log("command", kind=routed.command.value, text=content)
        if routed.command is Command.STOP:
            await self._do_stop()
            return
        if routed.command is Command.STATUS:
            await self.speak(self.session.status_text, sanitize=False)
            return
        if routed.command is Command.NOTE:
            await self._do_note(routed.text)
            return
        if routed.command is Command.BRIEFING:
            await self._enqueue_or_inject(self.strings.briefing_prompt)
            return
        await self._enqueue_or_inject(routed.text)

    async def _enqueue_or_inject(self, message: str) -> None:
        if self.session.working:
            # Steer the running turn directly — answered at the next step
            # boundary instead of waiting for the turn to finish.
            await self.speaker.earcon("ack")
            print("\033[2m  (in laufenden Turn eingeworfen)\033[0m", flush=True)
            self.logbook.log("interjection", text=message)
            await self.session.inject(message)
            return
        self._messages.put_nowait(message)

    async def _do_stop(self) -> None:
        self.speaker.stop()
        # Unconditional: a STOP landing in the retry gap (session.working is
        # briefly False during reconnect) must still abort the retry loop.
        self._interrupted_turn = True
        if self.session.working:
            await self.session.interrupt()
            self.logbook.log("interrupt")
            await self.speak(self.strings.stopped, sanitize=False)
            self._open_window()

    async def _do_note(self, note: str) -> None:
        """Flash note: capture a thought in <1s, ack with an earcon only."""
        path = Path(self.config.cwd) / (self.config.notes_file or self.strings.notes_file)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"- [ ] {note}  <!-- {stamp}, unterwegs diktiert -->\n")
            print(f"\033[32m📝 notiert: {note}\033[0m", flush=True)
            self.logbook.log("note", text=note)
            self.emit("note", text=note)
            await self.speaker.earcon("ack")
        except OSError as exc:
            print(f"\033[31mNotiz fehlgeschlagen: {exc}\033[0m", flush=True)
            await self.speaker.earcon("error")
            await self.speak(self.strings.note_failed, sanitize=False)

    async def _confirm_meant_me(self, text: str) -> None:
        """The window just closed but the driver clearly said something
        substantial — ask instead of silently dropping it."""
        async with self._permission_lock:
            self.logbook.log("grace_confirm", text=text)
            answer = await self._ask_and_await(
                self.strings.meant_me.format(text=text),
                timeout=12.0,
            )
            if answer is not None and parse_yes_no(answer, self.strings) is True:
                await self._dispatch(text)

    # ---------- permission dialog (called from inside a running turn) ----------

    async def _ask_permission(self, spoken_summary: str, raw: str = "") -> bool:
        if not self.interactive:
            print(f"\033[31m(auto-abgelehnt, kein Dialog möglich: {spoken_summary})\033[0m", flush=True)
            self.logbook.log("permission", summary=spoken_summary, decision="auto_deny")
            return False
        # The SDK spawns each permission request as its own task; without this
        # lock two questions would fight over one answer slot and the driver's
        # "Ja" could approve the wrong action.
        async with self._permission_lock:
            await self.speaker.earcon("attention")
            self.pending_permission = {"summary": spoken_summary, "raw": raw}
            self.emit("permission", summary=spoken_summary, raw=raw)
            question = self.strings.permission_question.format(summary=spoken_summary)
            prompt = question
            try:
                for _attempt in range(4):
                    answer = await self._ask_and_await(prompt, self.config.permission_timeout_s)
                    if answer is None:
                        await self.speak(self.strings.permission_no_answer, sanitize=False)
                        self.logbook.log("permission", summary=spoken_summary, decision="timeout_deny")
                        return False
                    extra = parse_permission_extra(answer, self.strings)
                    if extra == "repeat":
                        prompt = question
                        continue
                    if extra == "details":
                        prompt = self.strings.permission_details.format(detail=raw or spoken_summary)
                        continue
                    decision = parse_yes_no(answer, self.strings)
                    if decision is not None:
                        await self.speak(self.strings.permission_ok if decision else self.strings.permission_denied, sanitize=False)
                        self.logbook.log(
                            "permission", summary=spoken_summary, raw=raw,
                            decision="allow" if decision else "deny",
                        )
                        return decision
                    prompt = self.strings.permission_repeat_hint
                await self.speak(self.strings.permission_unclear, sanitize=False)
                self.logbook.log("permission", summary=spoken_summary, decision="unclear_deny")
                return False
            finally:
                self.pending_permission = None
                self.emit("permission", summary=None)

    async def _ask_and_await(self, question: str, timeout: float) -> str | None:
        # Future exists BEFORE the question plays: a fast answer right after
        # the playback ends must land in the dialog, not in the message queue.
        self._answer_future = asyncio.get_running_loop().create_future()
        self._answer_started_at = time.monotonic()
        self.emit("state", value="asking")
        # Phone UI: enable JA/NEIN for every spoken question (also the grace
        # dialog, which has no permission banner).
        self.emit("window", open=True, seconds=timeout)
        try:
            await self.speak(question, sanitize=False)
            # speak()'s finally emitted working/idle — restore the ask state
            # for the whole answer-wait period.
            self.emit("state", value="asking")
            return await asyncio.wait_for(self._answer_future, timeout)
        except TimeoutError:
            return None
        finally:
            self._answer_future = None
            self.emit("window", open=False)
            self.emit("state", value="working" if self.session.working else "idle")

    # ---------- turn execution ----------

    async def _turn_worker(self) -> None:
        while True:
            message = await self._messages.get()
            self._interrupted_turn = False
            await self.speaker.earcon("start")
            self.emit("state", value="working")
            result = await self._run_turn_with_retry(message)
            pending_injections = self.session.take_unanswered_injections()
            if result is not None and not self._interrupted_turn:
                # Re-queue only after a normal turn end. After a STOP the
                # driver aborted everything; after a failure they were told
                # to repeat — silently replaying would surprise them.
                for missed in pending_injections:
                    self._messages.put_nowait(missed)
            if result is None or self._interrupted_turn:
                self.emit("state", value="idle")
                continue
            try:
                await self._speak_result(result)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — must not kill the loop
                print(f"\033[31mFehler beim Vorlesen: {exc}\033[0m", flush=True)
            self.emit("state", value="idle")

    async def _run_turn_with_retry(self, message: str) -> TurnResult | None:
        """Dead-zone resilience: on failure reconnect once and re-send the
        message automatically — the driver must not re-dictate it. The retry
        is framed as reconciliation so half-executed side effects (edits,
        commits) are checked instead of blindly replayed."""
        for attempt in (1, 2):
            outbound = message if attempt == 1 else (
                self.strings.retry_reconcile.format(message=message)
            )
            try:
                started = time.monotonic()
                self.logbook.log("turn_start", message=message, attempt=attempt)
                result = await self.session.send(outbound)
                self.logbook.log(
                    "turn_end", elapsed_s=round(time.monotonic() - started, 1),
                    is_error=result.is_error,
                )
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"\033[31mFehler: {exc}\033[0m", flush=True)
                self.logbook.log("turn_error", error=str(exc)[:300], attempt=attempt)
                await self.speaker.earcon("error")
                if self._interrupted_turn:
                    return None  # driver said stop — no retry, no failure speech
                if attempt == 2:
                    break
                try:
                    await self.session.reconnect()
                except Exception as reconnect_exc:  # noqa: BLE001
                    print(f"\033[31mReconnect fehlgeschlagen: {reconnect_exc}\033[0m", flush=True)
                    break
                if self._interrupted_turn:
                    return None
                await self.speak(
                    self.strings.reconnecting, sanitize=False,
                )
        await self.speak(
            self.strings.connection_lost, sanitize=False,
        )
        self._open_window()
        return None

    async def _on_interjection_reply(self, text: str) -> None:
        """Speak the answer to a mid-turn interjection right away."""
        self._last_interim_spoken = text
        await self.speak(text)
        self._open_window()

    async def _speak_result(self, result: TurnResult) -> None:
        if result.is_error:
            await self.speaker.earcon("error")
        if result.text and result.text == self._last_interim_spoken:
            # The turn ended right after the interjection reply — it was
            # already spoken, don't repeat it.
            self._last_interim_spoken = ""
            print(f"\033[2m  (Turn: {result.elapsed_s:.0f}s)\033[0m", flush=True)
            return
        self._last_interim_spoken = ""
        if result.text:
            await self.speak(result.text)
        else:
            await self.speak(self.strings.no_answer_text, sanitize=False)
        print(f"\033[2m  (Turn: {result.elapsed_s:.0f}s)\033[0m", flush=True)
        if self._messages.empty():
            self._open_window()
            await self.speaker.earcon("listen")

    # ---------- modes ----------

    async def _startup(self, greeting: str) -> asyncio.Task:
        await self.session.start()
        worker = asyncio.create_task(self._turn_worker())
        await self.speak(greeting, sanitize=False)
        if self.config.continue_conversation or self.config.resume:
            # Orientation first: recap where we left off, spoken.
            self._messages.put_nowait(self.strings.recap_prompt)
        return worker

    async def _consume_utterances(self, utterances: asyncio.Queue, transcriber) -> None:
        while True:
            captured_end, audio = await utterances.get()
            # The segmenter stamps at emission (end of trailing silence); the
            # utterance STARTED len/rate seconds earlier — the echo gate needs
            # both ends to check overlap with TTS playback.
            captured_start = captured_end - len(audio) / self.config.sample_rate
            if not self._in_tts(captured_start, captured_end):
                await self.speaker.earcon("heard")  # "got you, transcribing"
            transcript = await transcriber.transcribe(audio)
            if transcript.text:
                self.logbook.log(
                    "utterance", text=transcript.text,
                    avg_logprob=round(transcript.avg_logprob, 2),
                    no_speech_prob=round(transcript.no_speech_prob, 2),
                )
                await self.handle_utterance(
                    transcript.text,
                    captured_at=captured_start,
                    captured_end=captured_end,
                    usable=transcript.usable,
                    confident=transcript.confident,
                )

    async def run_voice(self) -> None:
        from .audio import MicListener
        from .stt import Transcriber

        print("Lade Spracherkennung …", flush=True)
        transcriber = Transcriber(self.config.whisper_model, self.strings.stt_language, self.strings.stt_prompt)
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
        self.mic.start()
        worker = await self._startup(self.strings.greeting)
        stdin_task = asyncio.create_task(self._stdin_barge_in(_stdin_line_queue()))
        print("Sag »Claude …« — Enter stoppt die Sprachausgabe, q beendet.", flush=True)
        try:
            await self._consume_utterances(utterances, transcriber)
        finally:
            worker.cancel()
            stdin_task.cancel()
            if self._grace_task is not None:
                self._grace_task.cancel()
            self.mic.stop()
            self.logbook.close()
            await self.session.stop()

    async def run_phone(self) -> None:
        from .remote_audio import AudioServer
        from .stt import Transcriber

        print("Lade Spracherkennung …", flush=True)
        transcriber = Transcriber(self.config.whisper_model, self.strings.stt_language, self.strings.stt_prompt)
        utterances: asyncio.Queue = asyncio.Queue()
        server = AudioServer(self.config, self, utterances)
        self.speaker = server.speaker  # TTS now plays on the phone
        await server.start()
        # Greeting and --continue recap must reach ears — wait for the phone.
        print("Warte auf das Telefon …", flush=True)
        await server.wait_for_client()
        worker = await self._startup(self.strings.greeting)
        try:
            await self._consume_utterances(utterances, transcriber)
        finally:
            worker.cancel()
            if self._grace_task is not None:
                self._grace_task.cancel()
            await server.stop()
            self.logbook.close()
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
        worker = await self._startup(self.strings.typed_greeting)
        print("Tippen und Enter. Kommandos: stop, status, briefing, merk dir …, q.", flush=True)
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
                await self._dispatch(line)
        finally:
            worker.cancel()
            self.logbook.close()
            await self.session.stop()

    async def run_send_once(self, text: str) -> None:
        await self.session.start()
        try:
            result = await self.session.send(text)
            print(result.text)
            await self.speak(result.text)
        finally:
            self.logbook.close()
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
