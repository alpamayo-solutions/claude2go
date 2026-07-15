"""Confidence gates on Transcript: `usable` routes input, `confident` gates
permission answers. Constructed directly — no Whisper model involved."""

from claude_to_go.stt import Transcript

# ---------- usable ----------

def test_empty_text_never_usable():
    assert not Transcript("", 0.0, 0.0).usable


def test_good_transcript_usable():
    assert Transcript("mach die Tests grün", -0.3, 0.05).usable


def test_hallucination_gate_blocks_usable():
    # classic Whisper hallucination: high no-speech AND low logprob
    assert not Transcript("Untertitel im Auftrag des ZDF", -1.5, 0.9).usable


def test_usable_needs_both_conditions():
    # only one bad metric -> still usable
    assert Transcript("hallo", -1.5, 0.5).usable      # logprob bad, no_speech ok
    assert Transcript("hallo", -0.5, 0.9).usable      # no_speech bad, logprob ok


def test_usable_boundaries_are_exclusive():
    # gate fires only for no_speech_prob > 0.6 AND avg_logprob < -1.0
    assert Transcript("x", -1.0, 0.61).usable          # logprob exactly at -1.0
    assert Transcript("x", -1.01, 0.6).usable          # no_speech exactly at 0.6
    assert not Transcript("x", -1.01, 0.61).usable     # both just past the edge


# ---------- confident ----------

def test_empty_text_never_confident():
    assert not Transcript("", 0.0, 0.0).confident


def test_clear_speech_is_confident():
    assert Transcript("ja", -0.2, 0.1).confident


def test_confident_boundaries_are_strict():
    # requires no_speech_prob < 0.35 AND avg_logprob > -0.9
    assert not Transcript("ja", -0.9, 0.1).confident   # logprob exactly -0.9
    assert not Transcript("ja", -0.2, 0.35).confident  # no_speech exactly 0.35
    assert Transcript("ja", -0.89, 0.34).confident     # both just inside


def test_confident_is_stricter_than_usable():
    # mid-quality transcript: usable but not confident enough for consent
    t = Transcript("ja mach das", -0.95, 0.4)
    assert t.usable
    assert not t.confident
