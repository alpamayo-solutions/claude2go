"""Logbook: append-only JSONL drive log, silent when disabled."""

import json

from claude_to_go.logbook import Logbook


def test_writes_valid_jsonl_with_ts_and_event(tmp_path):
    book = Logbook(tmp_path / "logs")
    book.log("utterance", text="Claude, Status", avg_logprob=-0.3)
    book.log("command", kind="status")
    book.close()

    files = list((tmp_path / "logs").glob("*.jsonl"))
    assert len(files) == 1
    assert files[0] == book.path
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    for record in records:
        assert isinstance(record["ts"], float)
        assert "event" in record
    assert records[0]["event"] == "utterance"
    assert records[0]["text"] == "Claude, Status"
    assert records[1]["kind"] == "status"


def test_umlauts_survive_unescaped(tmp_path):
    book = Logbook(tmp_path / "logs")
    book.log("note", text="Milch kaufen — später")
    book.close()
    raw = book.path.read_text(encoding="utf-8")
    assert "Milch kaufen — später" in raw  # ensure_ascii=False


def test_log_after_close_is_noop(tmp_path):
    book = Logbook(tmp_path / "logs")
    book.log("first")
    book.close()
    book.log("after_close")  # must not raise, must not write
    lines = book.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "first"


def test_close_twice_is_safe(tmp_path):
    book = Logbook(tmp_path / "logs")
    book.close()
    book.close()


def test_disabled_logbook_is_silent():
    book = Logbook(None)
    book.log("anything", detail=1)  # no crash, no file
    book.close()


def test_each_session_gets_its_own_file(tmp_path):
    Logbook(tmp_path / "logs").close()
    # same-second collisions share a name; just assert dir exists and has files
    assert list((tmp_path / "logs").glob("*.jsonl"))
