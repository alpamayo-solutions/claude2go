"""Microphone capture and VAD-based utterance segmentation.

`UtteranceSegmenter` is transport-agnostic: it eats 30 ms int16 frames and
emits complete utterances. `MicListener` feeds it from the local microphone
(sounddevice callback thread); the phone frontend feeds it from a WebSocket.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable

import numpy as np
import sounddevice as sd

FRAME_MS = 30


class MicrophoneError(RuntimeError):
    pass


def find_input_device(name_substring: str) -> int:
    """Resolve an input device index by case-insensitive name substring."""
    matches = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name_substring.lower() in dev["name"].lower():
            matches.append((idx, dev["name"]))
    if not matches:
        available = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        raise MicrophoneError(
            f"Kein Eingabegerät passt auf {name_substring!r}. Verfügbar: {available}"
        )
    return matches[0][0]


class Vad:
    """webrtcvad if available, otherwise an adaptive RMS gate."""

    def __init__(self, aggressiveness: int, sample_rate: int) -> None:
        self._sample_rate = sample_rate
        try:
            import webrtcvad

            self._vad = webrtcvad.Vad(aggressiveness)
        except ImportError:
            self._vad = None
            self._noise_floor = 0.01

    def is_speech(self, frame: np.ndarray) -> bool:
        if self._vad is not None:
            return self._vad.is_speech(frame.tobytes(), self._sample_rate)
        rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768.0) ** 2)))
        voiced = rms > max(self._noise_floor * 3.0, 0.008)
        if not voiced:
            self._noise_floor = 0.95 * self._noise_floor + 0.05 * rms
        return voiced


class UtteranceSegmenter:
    """Segments a stream of int16 samples into utterances.

    Feed arbitrary-length sample chunks via `feed()`; complete utterances are
    passed to `on_utterance(captured_at_monotonic, samples)`. Thread-agnostic —
    the callback runs on whatever thread calls feed().
    """

    def __init__(
        self,
        vad,
        sample_rate: int,
        min_s: float,
        max_s: float,
        silence_end_ms: int,
        on_utterance: Callable[[float, np.ndarray], None],
    ) -> None:
        self._vad = vad
        self._frame_len = int(sample_rate * FRAME_MS / 1000)
        self._min_frames = int(min_s * 1000 / FRAME_MS)
        self._max_frames = int(max_s * 1000 / FRAME_MS)
        self._end_silence_frames = max(1, silence_end_ms // FRAME_MS)
        self._on_utterance = on_utterance

        self._preroll: deque[np.ndarray] = deque(maxlen=10)
        self._recent_voiced: deque[bool] = deque(maxlen=6)
        self._current: list[np.ndarray] = []
        self._preroll_frames = 0
        self._silence_run = 0
        self._residual = np.zeros(0, dtype=np.int16)

    def feed(self, samples: np.ndarray) -> None:
        samples = np.concatenate([self._residual, samples.astype(np.int16, copy=False)])
        n_full = len(samples) // self._frame_len
        for i in range(n_full):
            self._process_frame(samples[i * self._frame_len : (i + 1) * self._frame_len])
        self._residual = samples[n_full * self._frame_len :]

    def reset(self) -> None:
        self._current = []
        self._preroll_frames = 0
        self._silence_run = 0
        self._preroll.clear()
        self._recent_voiced.clear()
        self._residual = np.zeros(0, dtype=np.int16)

    def _process_frame(self, frame: np.ndarray) -> None:
        voiced = self._vad.is_speech(frame)
        self._recent_voiced.append(voiced)

        if not self._current:
            self._preroll.append(frame)
            if sum(self._recent_voiced) >= 4:  # utterance starts
                self._current = list(self._preroll)
                self._preroll_frames = len(self._current)
                self._silence_run = 0
            return

        self._current.append(frame)
        self._silence_run = 0 if voiced else self._silence_run + 1

        too_long = len(self._current) >= self._max_frames
        ended = self._silence_run >= self._end_silence_frames
        if ended or too_long:
            utterance = np.concatenate(self._current)
            # Preroll and trailing silence must not count toward the minimum —
            # otherwise 0.4s of context around a noise blip passes the gate.
            voiced_frames = len(self._current) - self._preroll_frames - self._silence_run
            self.reset()
            if voiced_frames >= self._min_frames:
                self._on_utterance(time.monotonic(), utterance)


class MicListener:
    """Feeds the local microphone into an UtteranceSegmenter.

    Queue items are ``(captured_at_monotonic, int16_array)``. `muted` drops
    audio entirely (typed mode etc.); during TTS the mic intentionally stays
    OPEN — the app routes those utterances through the stop-only gate.
    """

    def __init__(
        self,
        device_substring: str,
        sample_rate: int,
        vad_aggressiveness: int,
        min_s: float,
        max_s: float,
        silence_end_ms: int,
        loop: asyncio.AbstractEventLoop,
        out_queue: asyncio.Queue,
    ) -> None:
        self._loop = loop
        self._queue = out_queue
        self.muted = False
        self._segmenter = UtteranceSegmenter(
            vad=Vad(vad_aggressiveness, sample_rate),
            sample_rate=sample_rate,
            min_s=min_s,
            max_s=max_s,
            silence_end_ms=silence_end_ms,
            on_utterance=self._emit,
        )
        device = find_input_device(device_substring)
        self._stream = sd.InputStream(
            device=device,
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=int(sample_rate * FRAME_MS / 1000),
            callback=self._on_audio,
        )

    def start(self) -> None:
        self._stream.start()

    def stop(self) -> None:
        self._stream.stop()
        self._stream.close()

    # --- callback thread below this line ---

    def _emit(self, captured_at: float, utterance: np.ndarray) -> None:
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (captured_at, utterance))

    def _on_audio(self, indata: np.ndarray, frames: int, _time, status) -> None:
        if self.muted:
            self._segmenter.reset()
            return
        self._segmenter.feed(indata[:, 0].copy())
