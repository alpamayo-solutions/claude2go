"""Runtime configuration with sane zero-config defaults.

Precedence for every field: CLI flag > settings file (~/.c2g/config.toml) >
built-in default. The settings file lets a user pin (enforce) their language
and other preferences once instead of passing flags every time.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

SETTINGS_PATH = Path.home() / ".c2g" / "config.toml"


@dataclass
class Config:
    cwd: Path = field(default_factory=Path.cwd)
    model: str | None = None
    continue_conversation: bool = False
    resume: str | None = None  # session id to resume (None = don't)

    # Language of the whole voice interaction (STT, TTS, wake vocab, phrases)
    language: str = "de"

    # Audio in
    mic_device: str = "MacBook Pro Microphone"  # substring match; BlackHole is the default input on this machine
    sample_rate: int = 16_000
    vad_aggressiveness: int = 2
    utterance_min_s: float = 0.25  # a crisp "Ja" is ~0.3s — must pass the gate
    utterance_max_s: float = 30.0
    silence_end_ms: int = 800

    # STT
    whisper_model: str = "small"

    # TTS — None = best installed voice for the language locale
    voice: str | None = None
    speech_rate: int = 190
    mute: bool = False

    # Interaction
    answer_window_s: float = 20.0
    window_grace_s: float = 6.0    # "did you mean me?" period after the window closes
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

    # Flash notes land here (relative to cwd); None = language pack default
    notes_file: str | None = None


# Keys a user may set in ~/.c2g/config.toml (safe subset — no cwd/modes).
_SETTINGS_KEYS = {
    "model", "language", "mic_device", "whisper_model", "voice", "speech_rate",
    "answer_window_s", "window_grace_s", "permission_timeout_s",
    "phone_port", "notes_file", "vad_aggressiveness",
}


def load_settings(path: Path = SETTINGS_PATH) -> dict:
    """Read the user's persistent settings file, if any. Malformed files are
    reported and ignored rather than crashing the drive."""
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        print(f"\033[33m(Einstellungen in {path} ignoriert: {exc})\033[0m", flush=True)
        return {}
    return {k: v for k, v in data.items() if k in _SETTINGS_KEYS}


def apply_settings(config: Config, settings: dict) -> None:
    """Apply file settings onto a Config (only known fields)."""
    valid = {f.name for f in fields(Config)}
    for key, value in settings.items():
        if key in valid:
            setattr(config, key, value)
