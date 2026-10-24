"""Append-only JSONL timeline. One per run. Everything the dashboard, the report and the
demo video show comes from here, so write generously and never edit in place."""
from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path

from .types import TimelineEvent


class Timeline:
    def __init__(self, run_id: str | None = None, root: str | Path = "runs"):
        self.run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
        self.dir = Path(root) / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "timeline.jsonl"
        self._fh = open(self.path, "a", buffering=1)
        self._subscribers: list = []
        latest = Path(root) / "latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            os.symlink(self.run_id, latest)
        except OSError:
            pass

    def log(self, kind: str, **data) -> TimelineEvent:
        ev = TimelineEvent(kind=kind, data=data)
        self._fh.write(ev.model_dump_json() + "\n")
        for cb in list(self._subscribers):
            try:
                cb(ev)
            except Exception:
                pass
        return ev

    def subscribe(self, cb) -> None:
        self._subscribers.append(cb)

    def unsubscribe(self, cb) -> None:
        if cb in self._subscribers:
            self._subscribers.remove(cb)

    @staticmethod
    def read(path: str | Path) -> Iterator[TimelineEvent]:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield TimelineEvent(**json.loads(line))

    def close(self) -> None:
        self._fh.close()
