"""Speech output via macOS `say`, earcons via `afplay`, and text sanitizing."""

from __future__ import annotations

import asyncio
import re

_EARCONS = {
    "listen": "/System/Library/Sounds/Glass.aiff",   # answer window opened
    "ack": "/System/Library/Sounds/Pop.aiff",        # input accepted / queued
    "start": "/System/Library/Sounds/Hero.aiff",     # Claude starts working on a command
    "error": "/System/Library/Sounds/Basso.aiff",    # something went wrong
    "attention": "/System/Library/Sounds/Ping.aiff", # permission question incoming
}

_MAX_SPOKEN_CHARS = 700


def pick_best_german_voice() -> str:
    """Best installed German voice: Premium > Enhanced > Anna (compact)."""
    import subprocess

    listing = subprocess.run(
        ["say", "-v", "?"], capture_output=True, text=True
    ).stdout.splitlines()
    german = [line.split("  ")[0].strip() for line in listing if "de_DE" in line]
    for tier in ("(Premium)", "(Enhanced)"):
        for name in german:
            if tier in name:
                return name
    return "Anna"


def sanitize_for_speech(text: str) -> str:
    """Strip everything that is unbearable to listen to."""
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


class Speaker:
    """Interruptible TTS. `speaking` is True while audio is playing."""

    def __init__(self, voice: str | None, rate: int, mute: bool = False) -> None:
        self._voice = voice or pick_best_german_voice()
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
            self._proc = await asyncio.create_subprocess_exec(
                "say", "-v", self._voice, "-r", str(self._rate), spoken,
            )
            try:
                await self._proc.wait()
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
