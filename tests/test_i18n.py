"""Language packs are complete and the vocab/parsers work per language."""

import dataclasses

from claude_to_go.i18n import DEFAULT_LANGUAGE, LANGUAGES, get_strings
from claude_to_go.risk import classify
from claude_to_go.wake import Command, parse_command, parse_permission_extra, parse_yes_no


def test_default_is_german():
    assert DEFAULT_LANGUAGE == "de"
    assert get_strings("de").code == "de"


def test_unknown_language_falls_back_to_default():
    assert get_strings("fr").code == DEFAULT_LANGUAGE


def test_all_packs_have_every_field_filled():
    for code, strings in LANGUAGES.items():
        for f in dataclasses.fields(strings):
            value = getattr(strings, f.name)
            assert value not in (None, "", (), frozenset()), f"{code}.{f.name} empty"


def test_all_packs_share_the_same_risk_categories():
    de_keys = set(get_strings("de").risk_phrases)
    for code, strings in LANGUAGES.items():
        assert set(strings.risk_phrases) == de_keys, f"{code} risk categories differ"


def test_english_wake_and_commands():
    en = get_strings("en")
    assert parse_command("note buy milk", en).command is Command.NOTE
    assert parse_command("note buy milk", en).text == "buy milk"
    assert parse_command("status", en).command is Command.STATUS
    assert parse_command("briefing", en).command is Command.BRIEFING
    assert parse_command("stop", en).command is Command.STOP


def test_english_yes_no_and_extras():
    en = get_strings("en")
    assert parse_yes_no("yes go ahead", en) is True
    assert parse_yes_no("no way", en) is False
    assert parse_permission_extra("repeat", en) == "repeat"
    assert parse_permission_extra("details", en) == "details"


def test_english_risk_summary_is_english():
    en = get_strings("en")
    verdict = classify("Bash", {"command": "git push origin main"}, en)
    assert verdict.ask
    assert "push" in verdict.spoken_summary.lower()
    assert "origin main" in verdict.spoken_summary
    assert verdict.raw == "git push origin main"


def test_german_and_english_summaries_differ():
    de = classify("Bash", {"command": "rm -rf build"}, get_strings("de"))
    en = classify("Bash", {"command": "rm -rf build"}, get_strings("en"))
    assert "löschen" in de.spoken_summary
    assert "delete" in en.spoken_summary
