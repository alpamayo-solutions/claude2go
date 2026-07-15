"""App routing logic without audio, session, or network.

The real ClaudeSession and Speaker are replaced by recording fakes right
after construction; every scenario runs inside asyncio.run() (the project
deliberately has no pytest-asyncio dependency).
"""

import asyncio
import time

from claude_to_go.app import App
from claude_to_go.config import Config
from claude_to_go.prompts import BRIEFING_PROMPT


class FakeSession:
    def __init__(self):
        self.working = False
        self.status_text = "Ich bin bereit und warte auf dich."
        self.injected = []
        self.interrupts = 0
        self.sent = []

    async def inject(self, text):
        self.injected.append(text)

    async def interrupt(self):
        self.interrupts += 1

    async def send(self, text):
        self.sent.append(text)

    def take_unanswered_injections(self):
        return []


class FakeSpeaker:
    def __init__(self):
        self.said = []
        self.earcons = []
        self.stops = 0
        self.speaking = False

    async def say(self, text, sanitize=True):
        self.said.append(text)

    async def earcon(self, name):
        self.earcons.append(name)

    def stop(self):
        self.stops += 1


def build_app(tmp_path):
    config = Config(log_dir=None, mute=True, voice="Anna", cwd=tmp_path)
    app = App(config)
    app.session = FakeSession()
    app.speaker = FakeSpeaker()
    return app


def drain(queue):
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


async def wait_for_pending_future(app, timeout=2.0):
    """The permission dialog runs as a task; poll until its answer future
    is up (a fresh, not-yet-resolved one)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        fut = app._answer_future
        if fut is not None and not fut.done():
            return fut
        await asyncio.sleep(0.01)
    raise AssertionError("no pending answer future appeared")


async def answer(app, text, confident=True):
    """Simulate a spoken answer AFTER TTS playback ended: the fake say()
    returns instantly, so the +0.5s echo-slack interval around the question
    must be cleared or the answer would be dropped as echo."""
    fut = await wait_for_pending_future(app)
    app._tts_intervals.clear()
    await app.handle_utterance(text, confident=confident)
    return fut


# ---------- message routing ----------

def test_wake_message_while_idle_is_queued(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        await app.handle_utterance("Claude, erstelle einen Branch")
        assert drain(app._messages) == ["erstelle einen Branch"]
        assert app.session.injected == []

    asyncio.run(scenario())


def test_wake_message_while_working_is_injected(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        app.session.working = True
        await app.handle_utterance("Claude, erstelle einen Branch")
        assert app.session.injected == ["erstelle einen Branch"]
        assert drain(app._messages) == []
        assert "ack" in app.speaker.earcons

    asyncio.run(scenario())


def test_stop_while_working_interrupts(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        app.session.working = True
        await app.handle_utterance("Claude stopp")
        assert app.speaker.stops == 1
        assert app.session.interrupts == 1
        assert app._interrupted_turn is True
        assert any("gestoppt" in s for s in app.speaker.said)
        app._close_window()  # cancel the window-watch task before teardown
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_note_writes_file_and_acks_without_turn(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        await app.handle_utterance("Claude merk dir kauf milch")
        notes = (tmp_path / "NOTIZEN.md").read_text(encoding="utf-8")
        assert "- [ ] kauf milch" in notes
        assert "ack" in app.speaker.earcons
        assert drain(app._messages) == []
        assert app.session.injected == []

    asyncio.run(scenario())


def test_briefing_queues_briefing_prompt(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        await app.handle_utterance("Claude briefing")
        assert drain(app._messages) == [BRIEFING_PROMPT]

    asyncio.run(scenario())


def test_unusable_transcript_is_dropped(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        await app.handle_utterance("Claude mach irgendwas", usable=False)
        assert drain(app._messages) == []
        assert app.session.injected == []
        assert app._answer_future is None

    asyncio.run(scenario())


def test_unaddressed_speech_outside_window_is_ignored(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        await app.handle_utterance("und jetzt die Nachrichten um sechs")
        assert drain(app._messages) == []

    asyncio.run(scenario())


# ---------- permission dialog ----------

def test_permission_ja_allows(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        task = asyncio.create_task(app._ask_permission("X testen", "raw cmd"))
        await answer(app, "ja")
        assert await asyncio.wait_for(task, 2.0) is True
        assert any("Claude möchte X testen" in s for s in app.speaker.said)
        assert "attention" in app.speaker.earcons

    asyncio.run(scenario())


def test_permission_nein_denies(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        task = asyncio.create_task(app._ask_permission("X testen", "raw cmd"))
        await answer(app, "nein")
        assert await asyncio.wait_for(task, 2.0) is False

    asyncio.run(scenario())


def test_permission_wiederhole_repeats_question(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        task = asyncio.create_task(app._ask_permission("X testen", "raw cmd"))
        first = await answer(app, "wiederhole")
        # a NEW future must appear for the repeated question
        second = await wait_for_pending_future(app)
        assert second is not first
        await answer(app, "ja")
        assert await asyncio.wait_for(task, 2.0) is True
        question = "Claude möchte X testen. Ja oder Nein?"
        assert app.speaker.said.count(question) == 2

    asyncio.run(scenario())


def test_permission_details_reads_raw_command(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        task = asyncio.create_task(app._ask_permission("X testen", "raw cmd"))
        await answer(app, "details")
        await answer(app, "ja")
        assert await asyncio.wait_for(task, 2.0) is True
        assert any("raw cmd" in s for s in app.speaker.said)

    asyncio.run(scenario())


def test_permission_timeout_denies(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        app.config.permission_timeout_s = 0.3
        result = await asyncio.wait_for(
            app._ask_permission("X testen", "raw cmd"), 5.0
        )
        assert result is False
        assert any("Keine Antwort" in s for s in app.speaker.said)

    asyncio.run(scenario())


def test_unconfident_ja_is_not_consent(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        task = asyncio.create_task(app._ask_permission("X testen", "raw cmd"))
        fut = await answer(app, "ja", confident=False)
        assert not fut.done()  # still pending — the mumbled Ja did not count
        assert not task.done()
        await answer(app, "ja", confident=True)
        assert await asyncio.wait_for(task, 2.0) is True

    asyncio.run(scenario())


def test_permission_stop_denies_immediately(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        task = asyncio.create_task(app._ask_permission("X testen", "raw cmd"))
        await answer(app, "stopp")
        assert await asyncio.wait_for(task, 2.0) is False
        assert app.speaker.stops >= 1

    asyncio.run(scenario())


# ---------- barge-in during TTS ----------

def test_barge_in_stop_during_tts(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        now = time.monotonic()
        app._tts_intervals.append((now - 1.0, now + 5.0))
        await app.handle_utterance("Claude stopp", captured_at=now)
        assert app.speaker.stops == 1

    asyncio.run(scenario())


def test_bare_short_stop_during_tts_also_acts(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        now = time.monotonic()
        app._tts_intervals.append((now - 1.0, now + 5.0))
        await app.handle_utterance("stopp", captured_at=now)
        assert app.speaker.stops == 1

    asyncio.run(scenario())


def test_other_text_during_tts_is_dropped_as_echo(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        now = time.monotonic()
        app._tts_intervals.append((now - 1.0, now + 5.0))
        await app.handle_utterance("Claude erstelle einen Branch", captured_at=now)
        assert drain(app._messages) == []
        assert app.session.injected == []
        assert app.speaker.stops == 0

    asyncio.run(scenario())


# ---------- answer window & near-miss grace ----------

def test_open_window_routes_unaddressed_speech(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        app._window_until = time.monotonic() + 10.0
        await app.handle_utterance("erstelle einen Branch")
        assert drain(app._messages) == ["erstelle einen Branch"]

    asyncio.run(scenario())


def test_grace_window_asks_meintest_du_mich_then_dispatches(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        app.config.window_grace_s = 10.0
        app._window_until = time.monotonic() - 1.0  # window just closed
        # handle_utterance returns immediately; the dialog runs in _grace_task
        # so it cannot block the utterance-consumer loop.
        await app.handle_utterance("bitte auch die tests fixen", confident=True)
        assert app._grace_task is not None
        await wait_for_pending_future(app)
        assert any("Meintest du mich?" in s for s in app.speaker.said)
        await answer(app, "ja")
        await asyncio.wait_for(app._grace_task, 2.0)
        assert drain(app._messages) == ["bitte auch die tests fixen"]

    asyncio.run(scenario())


def test_grace_window_needs_confidence(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        app.config.window_grace_s = 10.0
        app._window_until = time.monotonic() - 1.0
        await app.handle_utterance("bitte auch die tests fixen", confident=False)
        assert app._answer_future is None  # no confirm dialog started
        assert drain(app._messages) == []

    asyncio.run(scenario())


def test_bare_wake_word_opens_window(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        await app.handle_utterance("Claude")
        assert app._window_until > time.monotonic()
        assert "listen" in app.speaker.earcons
        app._close_window()
        await asyncio.sleep(0)

    asyncio.run(scenario())


# ---------- status ----------

def test_status_command_speaks_session_status(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        await app.handle_utterance("Claude Status")
        assert app.session.status_text in app.speaker.said
        assert drain(app._messages) == []

    asyncio.run(scenario())


def test_echo_gate_catches_trailing_echo_by_overlap(tmp_path):
    # The segmenter stamps ~0.8s after the last voiced frame; an echo of the
    # assistant's reply must be caught even though its emission timestamp lies
    # OUTSIDE the recorded TTS interval — the utterance STARTED inside it.
    async def scenario():
        app = build_app(tmp_path)
        now = time.monotonic()
        app._tts_intervals.append((now - 3.0, now - 1.0))  # playback just ended
        app._window_until = now + 10.0  # answer window open (worst case)
        await app.handle_utterance(
            "die tests sind grün soll ich committen",
            captured_at=now - 2.0,   # started during playback
            captured_end=now - 0.2,  # emitted after the interval end
        )
        assert drain(app._messages) == []  # echo dropped, not dispatched

    asyncio.run(scenario())


def test_genuine_answer_after_tts_is_not_echo(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        now = time.monotonic()
        app._tts_intervals.append((now - 5.0, now - 2.0))
        app._window_until = now + 10.0
        await app.handle_utterance(
            "erstelle einen Branch",
            captured_at=now - 1.5,  # started after playback ended
            captured_end=now - 0.1,
        )
        assert drain(app._messages) == ["erstelle einen Branch"]

    asyncio.run(scenario())


def test_button_answer_bypasses_echo_gate(tmp_path):
    # A JA tap while the question is still playing is physical input, not echo.
    async def scenario():
        app = build_app(tmp_path)
        now = time.monotonic()
        app._current_tts_start = now - 0.5  # TTS playing right now
        task = asyncio.create_task(app._ask_permission("testen", "raw"))
        await wait_for_pending_future(app)
        await app.handle_utterance("ja", confident=True, from_button=True)
        assert await asyncio.wait_for(task, 2.0) is True

    asyncio.run(scenario())


def test_stop_during_retry_gap_aborts(tmp_path):
    async def scenario():
        app = build_app(tmp_path)
        app.session.working = False  # retry gap: no active turn
        await app._do_stop()
        assert app._interrupted_turn is True

    asyncio.run(scenario())
