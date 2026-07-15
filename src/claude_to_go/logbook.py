"""Append-only JSONL drive log — the data base for post-drive debugging and
tuning of wake words, VAD, and timeouts. One file per session."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


class Logbook:
    def __init__(self, log_dir: Path | None) -> None:
        self._file = None
        self.path: Path | None = None
        if log_dir is None:
            return
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            name = datetime.now().strftime("%Y%m%d-%H%M%S") + ".jsonl"
            self.path = log_dir / name
            # Long-lived handle by design; closed explicitly in close().
            self._file = open(self.path, "a", encoding="utf-8")  # noqa: SIM115
        except OSError as exc:
            print(f"\033[2m(drive log disabled: {exc})\033[0m", flush=True)
            self.path = None

    def log(self, event: str, **fields) -> None:
        if self._file is None:
            return
        record = {"ts": round(time.time(), 3), "event": event, **fields}
        try:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()
        except OSError:
            pass  # a full disk must never take down the voice loop

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            finally:
                self._file = None
