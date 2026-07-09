from claude_to_go.config import Config
from claude_to_go.wake import Command, match_wake, parse_command, parse_yes_no

WAKE = Config().wake_words


def test_wake_at_start():
    assert match_wake("Claude, mach die Tests grün", WAKE) == "mach die tests grün"


def test_hey_prefix():
    assert match_wake("Hey Claude erstelle einen Branch", WAKE) == "erstelle einen branch"


def test_whisper_variants():
    assert match_wake("Cloud, wie ist der Status?", WAKE) is not None
    assert match_wake("Klaut mach weiter", WAKE) is not None


def test_no_wake_mid_sentence():
    assert match_wake("ich habe claude gestern was gefragt", WAKE) is None


def test_radio_noise_ignored():
    assert match_wake("und jetzt die Nachrichten um sechs", WAKE) is None


def test_bare_wake_word():
    assert match_wake("Claude", WAKE) == ""


def test_command_stop():
    assert parse_command("stopp").command is Command.STOP
    assert parse_command("Stop!").command is Command.STOP


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


def test_yes_no():
    assert parse_yes_no("Ja, mach das") is True
    assert parse_yes_no("nein lieber nicht") is False
    assert parse_yes_no("hm was war die Frage") is None
    assert parse_yes_no("ja nein vielleicht") is None
