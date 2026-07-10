"""Runtime configuration with sane zero-config defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    cwd: Path = field(default_factory=Path.cwd)
    model: str | None = None
    continue_conversation: bool = False

    # Audio in
    mic_device: str = "MacBook Pro Microphone"  # substring match; BlackHole is the default input on this machine
    sample_rate: int = 16_000
    vad_aggressiveness: int = 2
    utterance_min_s: float = 0.25  # a crisp "Ja" is ~0.3s — must pass the gate
    utterance_max_s: float = 30.0
    silence_end_ms: int = 800

    # STT
    whisper_model: str = "small"
    stt_language: str = "de"

    # TTS — None = beste installierte deutsche Stimme (Premium > Enhanced > Anna)
    voice: str | None = None
    speech_rate: int = 190
    mute: bool = False

    # Interaction — "glaube" is deliberately absent: "ich glaube …" is far too
    # common in German conversation to be a wake variant.
    wake_words: tuple[str, ...] = ("claude", "cloud", "klaut", "klaud", "clod")
    answer_window_s: float = 20.0
    window_grace_s: float = 6.0    # "Meintest du mich?" period after the window closes
    permission_timeout_s: float = 30.0

    # Drive log (JSONL); None disables
    log_dir: Path | None = field(default_factory=lambda: Path.home() / ".c2g" / "logs")

    # Phone frontend
    phone: bool = False
    phone_port: int = 8443
    phone_http: bool = False  # plain HTTP (desktop testing via localhost only)

    # Modes
    typed: bool = False
    send_once: str | None = None

    # Flash notes land here (relative to cwd)
    notes_file: str = "NOTIZEN.md"
