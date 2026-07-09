from claude_to_go.tts import sanitize_for_speech


def test_strips_code_blocks():
    text = "Vorher.\n```python\nprint('hi')\n```\nNachher."
    result = sanitize_for_speech(text)
    assert "print" not in result
    assert "Codeblock übersprungen" in result


def test_strips_markdown():
    result = sanitize_for_speech("**Fett** und `code` und [Link](https://x.de)")
    assert result == "Fett und code und Link"


def test_bullets_become_prose():
    result = sanitize_for_speech("- erstens\n- zweitens")
    assert "-" not in result


def test_urls_replaced():
    assert "https" not in sanitize_for_speech("Siehe https://example.com/pfad")


def test_long_text_truncated():
    result = sanitize_for_speech("Wort " * 500)
    assert len(result) < 800
    assert result.endswith("Für Details frag nach.")


def test_plain_short_text_unchanged():
    assert sanitize_for_speech("Fertig. Wie machen wir weiter?") == "Fertig. Wie machen wir weiter?"
