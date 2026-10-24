"""Shared control plumbing. A workload runs as its own process and reads its control file at
step boundaries; knobs write that file. Status goes the other way. Files are written atomically
(write + rename) so a reader never sees half a JSON document.

Control file  runs/control/<job>.json         {"state": "run|pause|stop", "device": "gpu|cpu", "threads": n}
Status file   runs/control/<job>.status.json  {"state", "device", "progress", "rate", "t", ...}
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Protocol

from core.config import jobs as JOBS_CFG

WL = JOBS_CFG.get("workloads", {})
CONTROL_DIR = Path(WL.get("control_dir", "runs/control"))
CHECKPOINT_DIR = Path(WL.get("checkpoint_dir", "checkpoints"))


class WorkloadControl(Protocol):
    def status(self) -> dict: ...
    def start(self) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def set_concurrency(self, n: int) -> None: ...
    def set_threads(self, n: int) -> None: ...
    def set_device(self, device: str) -> None: ...


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def read_json(path: Path, default: dict | None = None) -> dict:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(default or {})


def control_path(job: str) -> Path:
    return CONTROL_DIR / f"{job}.json"


def status_path(job: str) -> Path:
    return CONTROL_DIR / f"{job}.status.json"


def mps_or_cpu(device: str) -> str:
    import torch
    return "mps" if device == "gpu" and torch.backends.mps.is_available() else "cpu"


class Worker:
    """Step loop with cooperative pause, device switch and thread count, driven by the control file."""

    job_id = ""

    def __init__(self):
        self.ctrl = {"state": "pause", "device": "gpu", "threads": os.cpu_count() or 4}
        self.device = None
        self.threads = None

    # subclasses implement these
    def load(self, device: str) -> None: ...
    def step(self) -> dict: ...                 # one unit of work; returns progress fields
    def checkpoint(self) -> None: ...
    def done(self) -> bool: return False

    def _apply(self):
        import torch
        c = read_json(control_path(self.job_id), self.ctrl)
        self.ctrl.update(c)
        if self.ctrl.get("threads") and self.ctrl["threads"] != self.threads:
            torch.set_num_threads(int(self.ctrl["threads"]))
            self.threads = int(self.ctrl["threads"])
        if self.ctrl["device"] != self.device and self.ctrl["state"] == "run":
            if self.device is not None:
                self.checkpoint()               # device switch = checkpoint, reload on the other device
            self.load(self.ctrl["device"])
            self.device = self.ctrl["device"]

    def _status(self, state: str, extra: dict):
        write_json(status_path(self.job_id), {"job": self.job_id, "state": state, "device": self.device,
                                              "threads": self.threads, "t": time.time(), "pid": os.getpid(), **extra})

    def run(self):
        last: dict = {}
        while True:
            self._apply()
            st = self.ctrl["state"]
            if st == "stop" or self.done():
                if self.device is not None:
                    self.checkpoint()
                self._status("done" if self.done() else "stopped", last)
                return
            if st == "pause":
                if self.device is not None and not last.get("paused_checkpointed"):
                    self.checkpoint()
                    last["paused_checkpointed"] = True
                self._status("paused", last)
                time.sleep(0.25)
                continue
            last = self.step()
            self._status("running", last)
