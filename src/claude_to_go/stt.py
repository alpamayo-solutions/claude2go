"""Local speech-to-text via faster-whisper. Fully offline after model download.

Every transcript carries confidence metadata: Whisper hallucinate text on
road noise, and a hallucination must never grant a permission or become a
command. `usable` gates general input, `confident` gates permission answers.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np

# Bias transcription toward the vocabulary we actually expect in the car.
# Vocabulary only — no imperative phrases: Whisper regurgitates prompt
# fragments as hallucinations on noise, and a hallucinated command would
# self-trigger a turn.
_INITIAL_PROMPT = (
    "Claude. Git, Branch, Commit, Push, Deploy, Test, Bug, PREKIT, "
    "Software-Entwicklung auf Deutsch."
)


@dataclass
class Transcript:
    text: str
    avg_logprob: float
    no_speech_prob: float

    @property
    def usable(self) -> bool:
        """Good enough to route as input (classic Whisper hallucination gate)."""
        if not self.text:
            return False
        return not (self.no_speech_prob > 0.6 and self.avg_logprob < -1.0)

    @property
    def confident(self) -> bool:
        """Strict gate for consequential input (permission answers)."""
        if not self.text:
            return False
        return self.no_speech_prob < 0.35 and self.avg_logprob > -0.9


class Transcriber:
    def __init__(self, model_name: str, language: str) -> None:
        from faster_whisper import WhisperModel  # heavy import, keep local

        self._model = WhisperModel(model_name, device="cpu", compute_type="int8")
        self._language = language

    def transcribe_sync(self, audio_f32: np.ndarray) -> Transcript:
        segments, _info = self._model.transcribe(
            audio_f32,
            language=self._language,
            beam_size=2,
            initial_prompt=_INITIAL_PROMPT,
            condition_on_previous_text=False,
            vad_filter=False,  # we already segment with our own VAD
        )
        segments = list(segments)
        if not segments:
            return Transcript("", -10.0, 1.0)
        text = " ".join(s.text for s in segments).strip()
        # Worst segment decides: one hallucinated segment poisons the whole
        # utterance for gating purposes.
        return Transcript(
            text=text,
            avg_logprob=min(s.avg_logprob for s in segments),
            no_speech_prob=max(s.no_speech_prob for s in segments),
        )

    async def transcribe(self, audio_int16: np.ndarray) -> Transcript:
        """Async wrapper; STT runs in a worker thread to keep the loop live."""
        audio_f32 = audio_int16.astype(np.float32) / 32768.0
        return await asyncio.to_thread(self.transcribe_sync, audio_f32)
