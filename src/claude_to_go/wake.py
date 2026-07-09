"""Wake-word matching and voice-command parsing on STT transcripts."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache


class Command(Enum):
    STOP = "stop"
    STATUS = "status"
    MESSAGE = "message"


@dataclass
class Routed:
    command: Command
    text: str  # remaining content with wake word stripped


_STOP_WORDS = {"stopp", "stop", "halt", "abbrechen", "abbruch"}
_STOP_PHRASES = ("hör auf", "hoer auf")
_STATUS_WORDS = {"status", "zwischenstand", "stand"}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[^\w\s]", "", text).strip()


@lru_cache(maxsize=8)
def _wake_re(wake_words: tuple[str, ...]) -> re.Pattern:
    words = "|".join(re.escape(w) for w in wake_words)
    # Wake word must open the utterance (optionally after a greeting) — a
    # variant appearing mid-sentence ("ich glaube …", "die Cloud …") must NOT
    # trigger. Returns the rest in original casing/punctuation, so file names
    # and version numbers survive ("app.py", "v2.1").
    return re.compile(
        rf"^\W*(?:(?:hey|hi|hallo|he|ey)[\s,]+)?(?:{words})\b[,.!?:;]*\s*(?P<rest>.*)$",
        re.IGNORECASE,
    )


def match_wake(text: str, wake_words: tuple[str, ...]) -> str | None:
    """Return the utterance content after the wake word, or None if not addressed."""
    match = _wake_re(tuple(wake_words)).match(text.strip())
    if match is None:
        return None
    return match.group("rest").strip()


def parse_command(content: str) -> Routed:
    """Classify addressed content into stop/status/message.

    Stop/status must be short utterances — a stop word inside a longer
    instruction ("stopp die Tests nicht, sondern …") stays a message.
    """
    normalized = _normalize(content)
    tokens = normalized.split()
    if tokens and len(tokens) <= 4:
        if any(t in _STOP_WORDS for t in tokens[:2]) or any(
            normalized.startswith(p) or f" {p}" in normalized for p in _STOP_PHRASES
        ):
            return Routed(Command.STOP, "")
        if len(tokens) <= 3 and any(t in _STATUS_WORDS for t in tokens[:2]):
            return Routed(Command.STATUS, "")
    return Routed(Command.MESSAGE, content.strip())


# Deliberately narrow: these words grant destructive actions while driving.
# Everyday conversational German ("mach", "gut", "klar", "passt") must NOT
# count as consent — ambient passenger/radio speech would trigger it.
_YES_WORDS = {
    "ja", "jawohl", "jo", "jap", "yes", "yep", "okay", "ok",
    "erlaubt", "erlauben", "einverstanden", "freigeben", "genehmigt",
}
_NO_WORDS = {
    "nein", "ne", "nee", "nö", "no", "nope", "nicht", "stopp", "stop", "lass",
    "ablehnen", "abgelehnt", "verboten", "niemals", "warte", "abbrechen",
}


def parse_yes_no(text: str) -> bool | None:
    """Parse a spoken German yes/no answer. None means unclear.

    Long utterances are never treated as answers — an in-flight command
    sentence must not accidentally approve a risky action.
    """
    tokens = _normalize(text).split()
    if not tokens or len(tokens) > 4:
        return None
    token_set = set(tokens)
    yes = bool(token_set & _YES_WORDS)
    no = bool(token_set & _NO_WORDS)
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None
