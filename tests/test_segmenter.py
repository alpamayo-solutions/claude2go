"""UtteranceSegmenter with a scripted VAD stub — no microphone, no webrtcvad."""

import numpy as np

from claude_to_go.audio import FRAME_MS, UtteranceSegmenter

SAMPLE_RATE = 16_000
FRAME_LEN = SAMPLE_RATE * FRAME_MS // 1000  # 480 samples


class ScriptedVad:
    """is_speech returns the scripted booleans in order, then False forever."""

    def __init__(self, script):
        self._script = list(script)

    def is_speech(self, frame):
        return self._script.pop(0) if self._script else False


def _make(script, min_s=0.3, max_s=30.0, silence_end_ms=300):
    emitted = []
    seg = UtteranceSegmenter(
        vad=ScriptedVad(script),
        sample_rate=SAMPLE_RATE,
        min_s=min_s,           # -> 10 frames minimum voiced
        max_s=max_s,
        silence_end_ms=silence_end_ms,  # -> 10 frames of end silence
        on_utterance=lambda t, u: emitted.append((t, u)),
    )
    return seg, emitted


def _frames(n, value=1000):
    return np.full(n * FRAME_LEN, value, dtype=np.int16)


def test_utterance_emitted_after_speech_and_end_silence():
    # 4 voiced to trigger start, 14 more voiced, 10 silence to end.
    seg, emitted = _make([True] * 18 + [False] * 10)
    seg.feed(_frames(28))
    assert len(emitted) == 1
    captured_at, utterance = emitted[0]
    assert isinstance(captured_at, float)
    assert utterance.dtype == np.int16
    # 4 preroll frames + 24 fed after start = 28 frames total
    assert len(utterance) == 28 * FRAME_LEN


def test_short_blip_not_emitted():
    # Only the 4 start-trigger frames (preroll), then silence: voiced count
    # after subtracting preroll and trailing silence is 0 < min_frames.
    seg, emitted = _make([True] * 4 + [False] * 10)
    seg.feed(_frames(14))
    assert emitted == []


def test_max_length_force_cut():
    # Continuous speech, never any silence — cut at max_frames.
    max_s = 0.6  # -> 20 frames
    seg, emitted = _make([True] * 25, min_s=0.3, max_s=max_s)
    seg.feed(_frames(25))
    assert len(emitted) == 1
    _t, utterance = emitted[0]
    assert len(utterance) == 20 * FRAME_LEN
    # voiced_frames = 4 trigger + 16 following = 20 >= 10


def test_reset_drops_in_progress_utterance():
    seg, emitted = _make([True] * 8 + [False] * 20)
    seg.feed(_frames(8))          # utterance started, in progress
    assert seg._current           # sanity: something is buffered
    seg.reset()
    seg.feed(_frames(20))         # remaining script: silence tail only
    assert emitted == []
    assert len(seg._residual) == 0


def test_residual_handling_with_odd_chunk_sizes():
    # Same audio as the happy path, but delivered in 100-sample chunks.
    seg, emitted = _make([True] * 18 + [False] * 10)
    total = _frames(28)
    for i in range(0, len(total), 100):
        seg.feed(total[i : i + 100])
    assert len(emitted) == 1
    assert len(emitted[0][1]) == 28 * FRAME_LEN


def test_residual_carries_partial_frames():
    seg, emitted = _make([True] * 18 + [False] * 10)
    seg.feed(_frames(1)[: FRAME_LEN - 1])  # not a full frame yet
    assert len(seg._residual) == FRAME_LEN - 1
    seg.feed(np.zeros(1, dtype=np.int16))  # completes exactly one frame
    assert len(seg._residual) == 0


def test_captured_at_is_monotonic_float():
    import time

    seg, emitted = _make([True] * 18 + [False] * 10)
    before = time.monotonic()
    seg.feed(_frames(28))
    after = time.monotonic()
    captured_at = emitted[0][0]
    assert isinstance(captured_at, float)
    assert before <= captured_at <= after


def test_float_input_is_coerced_to_int16():
    # feed() casts via astype(int16, copy=False); values survive.
    seg, emitted = _make([True] * 18 + [False] * 10)
    seg.feed(np.full(28 * FRAME_LEN, 1000.0))
    assert len(emitted) == 1
    assert emitted[0][1].dtype == np.int16
    assert emitted[0][1][0] == 1000
