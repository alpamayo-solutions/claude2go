"""Local speech-to-text via faster-whisper. Fully offline after model download."""

from __future__ import annotations

import asyncio

import numpy as np

# Bias transcription toward the vocabulary we actually expect in the car.
# Vocabulary only — no imperative phrases: Whisper regurgitates prompt
# fragments as hallucinations on noise, and a hallucinated command would
# self-trigger a turn.
_INITIAL_PROMPT = (
    "Claude. Git, Branch, Commit, Push, Deploy, Test, Bug, PREKIT, "
    "Software-Entwicklung auf Deutsch."
)


class Transcriber:
    def __init__(self, model_name: str, language: str) -> None:
        from faster_whisper import WhisperModel  # heavy import, keep local

        self._model = WhisperModel(model_name, device="cpu", compute_type="int8")
        self._language = language

    def transcribe_sync(self, audio_f32: np.ndarray) -> str:
        segments, _info = self._model.transcribe(
            audio_f32,
            language=self._language,
            beam_size=2,
            initial_prompt=_INITIAL_PROMPT,
            condition_on_previous_text=False,
            vad_filter=False,  # we already segment with our own VAD
        )
        return " ".join(s.text for s in segments).strip()

    async def transcribe(self, audio_int16: np.ndarray) -> str:
        """Async wrapper; STT runs in a worker thread to keep the loop live."""
        audio_f32 = audio_int16.astype(np.float32) / 32768.0
        return await asyncio.to_thread(self.transcribe_sync, audio_f32)
