"""Wake-word matching and voice-command parsing on STT transcripts."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class Command(Enum):
    STOP = "stop"
    STATUS = "status"
    MESSAGE = "message"


@dataclass
class Routed:
    command: Command
    text: str  # remaining content with wake word stripped


_STOP_WORDS = {"stopp", "stop", "halt", "abbrechen", "abbruch"}
_STATUS_WORDS = {"status", "zwischenstand", "stand"}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[^\w\s]", "", text).strip()


def match_wake(text: str, wake_words: tuple[str, ...]) -> str | None:
    """Return the utterance content after the wake word, or None if no wake word.

    The wake word must be one of the first two tokens — "hey claude mach X"
    and "claude mach X" both match; "ich habe claude gesagt" does not.
    """
    tokens = _normalize(text).split()
    for i, token in enumerate(tokens[:2]):
        if token in wake_words:
            return " ".join(tokens[i + 1 :]).strip()
    return None


def parse_command(content: str) -> Routed:
    """Classify wake-word-addressed content into stop/status/message."""
    tokens = _normalize(content).split()
    if tokens and len(tokens) <= 2:
        if tokens[0] in _STOP_WORDS:
            return Routed(Command.STOP, "")
        if tokens[0] in _STATUS_WORDS:
            return Routed(Command.STATUS, "")
    return Routed(Command.MESSAGE, content.strip())


_YES_WORDS = {
    "ja", "jawohl", "jo", "jap", "yes", "yep", "klar", "genau", "okay", "ok",
    "mach", "machen", "erlaubt", "erlauben", "freigeben", "los", "go", "gerne",
    "bitte", "einverstanden", "passt", "gut",
}
_NO_WORDS = {
    "nein", "ne", "nee", "nö", "no", "nope", "nicht", "stopp", "stop", "lass",
    "ablehnen", "abgelehnt", "verboten", "niemals", "warte", "abbrechen",
}


def parse_yes_no(text: str) -> bool | None:
    """Parse a spoken German yes/no answer. None means unclear."""
    tokens = set(_normalize(text).split())
    yes = bool(tokens & _YES_WORDS)
    no = bool(tokens & _NO_WORDS)
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None
