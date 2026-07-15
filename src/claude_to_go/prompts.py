"""Prompt text now lives in the language packs (see i18n.py).

These module-level names are kept as the German defaults so any older import
keeps working; the app reads them from the active `Strings` pack instead.
"""

from .i18n import get_strings

_DE = get_strings("de")

VOICE_STYLE = _DE.voice_style
RECAP_PROMPT = _DE.recap_prompt
BRIEFING_PROMPT = _DE.briefing_prompt
