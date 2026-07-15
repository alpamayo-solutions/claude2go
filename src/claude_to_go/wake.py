"""Wake-word matching and voice-command parsing on STT transcripts.

All vocabulary comes from a language pack (`i18n.Strings`); it defaults to the
German pack so existing callers and tests keep working without passing one.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from .i18n import Strings, get_strings

_DEFAULT = get_strings("de")


class Command(Enum):
    STOP = "stop"
    STATUS = "status"
    NOTE = "note"          # "merk dir …" — flash note, no Claude turn
    BRIEFING = "briefing"  # curated morning briefing turn
    MESSAGE = "message"


@dataclass
class Routed:
    command: Command
    text: str  # remaining content with wake word stripped


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


def parse_command(content: str, strings: Strings = _DEFAULT) -> Routed:
    """Classify addressed content into stop/status/note/briefing/message.

    Stop/status/briefing must be short utterances — a keyword inside a longer
    instruction stays a message.
    """
    normalized = _normalize(content)
    tokens = normalized.split()
    if tokens and len(tokens) <= 4:
        if any(t in strings.stop_words for t in tokens[:2]) or any(
            normalized.startswith(p) or f" {p}" in normalized for p in strings.stop_phrases
        ):
            return Routed(Command.STOP, "")
        if len(tokens) <= 3 and any(t in strings.status_words for t in tokens[:2]):
            return Routed(Command.STATUS, "")
        if len(tokens) <= 3 and any(t in strings.briefing_words for t in tokens[:2]):
            return Routed(Command.BRIEFING, "")
    for prefix in strings.note_prefixes:
        if normalized.startswith(prefix):
            # keep the note text in original casing/punctuation
            note = content.strip()[len(prefix):].lstrip(" ,.:;—-")
            if note:
                return Routed(Command.NOTE, note)
    return Routed(Command.MESSAGE, content.strip())


def parse_permission_extra(text: str, strings: Strings = _DEFAULT) -> str | None:
    """Detect 'repeat the question' / 'read the raw command' requests."""
    normalized = _normalize(text)
    tokens = normalized.split()
    if not tokens or len(tokens) > 5:
        return None
    if any(t in strings.repeat_words for t in tokens):
        return "repeat"
    if any(t in strings.detail_words for t in tokens):
        return "details"
    return None


def parse_yes_no(text: str, strings: Strings = _DEFAULT) -> bool | None:
    """Parse a spoken yes/no answer. None means unclear.

    Long utterances are never treated as answers — an in-flight command
    sentence must not accidentally approve a risky action.
    """
    tokens = _normalize(text).split()
    if not tokens or len(tokens) > 4:
        return None
    token_set = set(tokens)
    yes = bool(token_set & strings.yes_words)
    no = bool(token_set & strings.no_words)
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None
