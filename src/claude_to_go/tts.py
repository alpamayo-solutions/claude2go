"""Speech output via macOS `say`, earcons via `afplay`, and text sanitizing."""

from __future__ import annotations

import asyncio
import re

_EARCONS = {
    "listen": "/System/Library/Sounds/Glass.aiff",       # answer window opened
    "ack": "/System/Library/Sounds/Pop.aiff",            # input accepted / queued
    "heard": "/System/Library/Sounds/Tink.aiff",         # utterance captured, STT running
    "start": "/System/Library/Sounds/Hero.aiff",         # Claude starts working on a command
    "window_close": "/System/Library/Sounds/Bottle.aiff",# answer window just closed
    "error": "/System/Library/Sounds/Basso.aiff",        # something went wrong
    "attention": "/System/Library/Sounds/Ping.aiff",     # permission question incoming
}
EARCON_NAMES = tuple(_EARCONS)

_MAX_SPOKEN_CHARS = 700


def pick_best_voice(locale: str = "de_DE", fallback: str = "Anna") -> str:
    """Best installed voice for a locale: Premium > Enhanced > any > fallback."""
    import subprocess

    try:
        # Fixed argv, macOS system tool ("say"), no user input.
        listing = subprocess.run(  # nosec B603 B607
            ["say", "-v", "?"], capture_output=True, text=True
        ).stdout.splitlines()
    except OSError:
        return fallback
    matches = [line.split("  ")[0].strip() for line in listing if locale in line]
    for tier in ("(Premium)", "(Enhanced)"):
        for name in matches:
            if tier in name:
                return name
    return matches[0] if matches else fallback


# Backwards-compatible alias (older callers/tests).
def pick_best_german_voice() -> str:
    return pick_best_voice("de_DE", "Anna")


def sanitize_for_speech(text: str) -> str:
    """Strip everything that is unbearable to listen to."""
    if text.count("```") % 2 == 1:
        text += "\n```"  # unclosed fence (truncated output) must still be stripped
    text = re.sub(r"```.*?```", " Codeblock übersprungen. ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*?|__?", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # links -> label
    text = re.sub(r"https?://\S+", "Link", text)
    text = " ".join(text.split())
    if len(text) > _MAX_SPOKEN_CHARS:
        text = text[:_MAX_SPOKEN_CHARS].rsplit(" ", 1)[0] + " … Für Details frag nach."
    return text.strip()


async def render_wav(voice: str, rate: int, text: str) -> bytes:
    """Render text to a 22.05 kHz mono 16-bit WAV via `say -o` (for the phone
    frontend, which plays audio itself instead of the Mac speakers)."""
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        out_path = Path(f.name)
    try:
        proc = await asyncio.create_subprocess_exec(
            "say", "-v", voice, "-r", str(rate),
            "-o", str(out_path), "--data-format=LEI16@22050",
            stdin=asyncio.subprocess.PIPE,
        )
        proc.stdin.write(text.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.wait()
        return out_path.read_bytes()
    finally:
        out_path.unlink(missing_ok=True)


class Speaker:
    """Interruptible TTS. `speaking` is True while audio is playing."""

    def __init__(
        self, voice: str | None, rate: int, mute: bool = False,
        locale: str = "de_DE", fallback: str = "Anna",
    ) -> None:
        self._voice = voice or pick_best_voice(locale, fallback)
        self._rate = rate
        self._mute = mute
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    @property
    def speaking(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def say(self, text: str, sanitize: bool = True) -> None:
        """Speak text; returns when playback finished or was interrupted."""
        spoken = sanitize_for_speech(text) if sanitize else text.strip()
        if not spoken:
            return
        print(f"\033[36m🔊 {spoken}\033[0m", flush=True)
        if self._mute:
            return
        async with self._lock:
            # Text goes via stdin — passing it as an argv would let replies
            # starting with "-" be parsed as `say` options (verified: writes
            # files via -o instead of speaking).
            proc = await asyncio.create_subprocess_exec(
                "say", "-v", self._voice, "-r", str(self._rate),
                stdin=asyncio.subprocess.PIPE,
            )
            self._proc = proc
            try:
                proc.stdin.write(spoken.encode())
                await proc.stdin.drain()
                proc.stdin.close()
                await proc.wait()
            except asyncio.CancelledError:
                proc.kill()
                raise
            finally:
                self._proc = None

    def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.kill()

    async def earcon(self, name: str) -> None:
        if self._mute:
            return
        path = _EARCONS.get(name)
        if not path:
            return
        # Fire and forget; earcons must never block the pipeline.
        await asyncio.create_subprocess_exec(
            "afplay", path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
