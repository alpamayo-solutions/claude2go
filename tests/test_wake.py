from claude_to_go.config import Config
from claude_to_go.wake import (
    Command,
    match_wake,
    parse_command,
    parse_permission_extra,
    parse_yes_no,
)

WAKE = Config().wake_words


def test_wake_at_start():
    assert match_wake("Claude, mach die Tests grün", WAKE) == "mach die Tests grün"


def test_hey_prefix():
    assert match_wake("Hey Claude erstelle einen Branch", WAKE) == "erstelle einen Branch"


def test_content_keeps_punctuation_and_casing():
    assert match_wake("Claude, öffne app.py in Version 2.1", WAKE) == "öffne app.py in Version 2.1"


def test_whisper_variants():
    assert match_wake("Cloud, wie ist der Status?", WAKE) is not None
    assert match_wake("Klaut mach weiter", WAKE) is not None


def test_no_wake_mid_sentence():
    assert match_wake("ich habe claude gestern was gefragt", WAKE) is None


def test_ich_glaube_is_not_wake():
    assert match_wake("Ich glaube das dauert noch", WAKE) is None


def test_die_cloud_is_not_wake():
    assert match_wake("Die Cloud ist heute langsam", WAKE) is None


def test_radio_noise_ignored():
    assert match_wake("und jetzt die Nachrichten um sechs", WAKE) is None


def test_bare_wake_word():
    assert match_wake("Claude", WAKE) == ""
    assert match_wake("Claude.", WAKE) == ""


def test_command_stop():
    assert parse_command("stopp").command is Command.STOP
    assert parse_command("Stop!").command is Command.STOP
    assert parse_command("bitte stopp").command is Command.STOP
    assert parse_command("hör auf").command is Command.STOP
    assert parse_command("stopp die Tests").command is Command.STOP


def test_command_status():
    assert parse_command("Status").command is Command.STATUS
    assert parse_command("Zwischenstand bitte").command is Command.STATUS


def test_command_message():
    routed = parse_command("erstelle einen neuen Branch und fixe den Bug")
    assert routed.command is Command.MESSAGE
    assert "Branch" in routed.text


def test_stop_inside_long_sentence_is_message():
    routed = parse_command("stopp die Tests nicht, sondern erweitere sie")
    assert routed.command is Command.MESSAGE


def test_command_note_merk_dir():
    routed = parse_command("merk dir kauf Milch")
    assert routed.command is Command.NOTE
    assert routed.text == "kauf Milch"


def test_command_note_notiere():
    routed = parse_command("notiere kauf milch")
    assert routed.command is Command.NOTE
    assert routed.text == "kauf milch"


def test_note_keeps_original_casing_after_punctuation():
    routed = parse_command("Merk dir: PREKIT Demo vorbereiten")
    assert routed.command is Command.NOTE
    assert routed.text == "PREKIT Demo vorbereiten"


def test_bare_note_prefix_without_text_is_message():
    # "merk dir" with nothing to note must not create an empty note
    assert parse_command("merk dir").command is not Command.NOTE


def test_command_briefing():
    assert parse_command("briefing").command is Command.BRIEFING
    assert parse_command("Lagebericht bitte").command is Command.BRIEFING


def test_briefing_inside_long_sentence_is_message():
    routed = parse_command("gib mir bitte ein ausführliches briefing zum Projektstand")
    assert routed.command is Command.MESSAGE


def test_permission_extra_repeat():
    assert parse_permission_extra("wiederhole") == "repeat"
    assert parse_permission_extra("nochmal") == "repeat"


def test_permission_extra_details():
    assert parse_permission_extra("details") == "details"
    assert parse_permission_extra("welcher Befehl") == "details"


def test_permission_extra_long_sentence_is_none():
    assert parse_permission_extra(
        "kannst du mir das bitte noch einmal komplett vorlesen"
    ) is None


def test_permission_extra_plain_answer_is_none():
    assert parse_permission_extra("ja") is None
    assert parse_permission_extra("nein") is None


def test_yes_no():
    assert parse_yes_no("Ja, mach das") is True
    assert parse_yes_no("nein lieber nicht") is False
    assert parse_yes_no("hm was war die Frage") is None
    assert parse_yes_no("ja nein vielleicht") is None


def test_long_sentence_is_never_consent():
    # a buffered command must not approve a risky action
    assert parse_yes_no("Claude mach die Tests grün und push danach") is None


def test_common_conversation_words_are_not_consent():
    for phrase in ["mach weiter", "gut so", "klar doch", "passt schon", "bitte sehr"]:
        assert parse_yes_no(phrase) is None, phrase
