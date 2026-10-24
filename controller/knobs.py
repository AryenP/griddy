"""The only code path to the workloads' knobs. Every call is idempotent (writes the desired
state; the workload converges to it) and logged as an `action` event when a timeline is given.
Workloads run as child processes started here."""
from __future__ import annotations

import os
import subprocess
import sys
import time

from core.timeline import Timeline
from workloads.base import control_path, read_json, status_path, write_json

MODULES = {"chat": "workloads.chat_proxy", "train": "workloads.train", "batch": "workloads.batch"}


class Knobs:
    def __init__(self, timeline: Timeline | None = None, log_dir: str = "runs/logs", env: dict | None = None):
        self.tl, self.log_dir, self.env = timeline, log_dir, env
        self.procs: dict[str, subprocess.Popen] = {}

    def _set(self, job: str, **changes) -> dict:
        cur = read_json(control_path(job))
        new = {**cur, **changes}
        if new != cur:
            write_json(control_path(job), new)
            if self.tl:
                self.tl.log("action", job=job, **changes, previous={k: cur.get(k) for k in changes})
        return new

    # ---- process lifecycle
    def start(self, job: str, paused: bool = True) -> None:
        """Start the workload process if not running. Batch jobs start paused by default."""
        if job != "chat":
            self._set(job, state="pause" if paused else "run")
        p = self.procs.get(job)
        if p and p.poll() is None:
            return
        os.makedirs(self.log_dir, exist_ok=True)
        log = open(f"{self.log_dir}/{job}.log", "a")
        env = {**os.environ, **self.env} if self.env else None
        self.procs[job] = subprocess.Popen([sys.executable, "-m", MODULES[job]], stdout=log, stderr=subprocess.STDOUT,
                                           env=env)

    def stop_all(self, timeout: float = 15) -> None:
        for job in ("train", "batch"):
            if job in self.procs:
                self._set(job, state="stop")
        t = time.time()
        for job, p in self.procs.items():
            if job == "chat":
                p.terminate()
            while p.poll() is None and time.time() - t < timeout:
                time.sleep(0.2)
            if p.poll() is None:
                p.kill()

    # ---- knobs (SPEC §6)
    def run(self, job: str) -> dict:
        return self._set(job, state="run")

    def pause(self, job: str) -> dict:
        return self._set(job, state="pause")

    resume = run

    def set_concurrency(self, job: str, n: int) -> dict:
        if job != "chat":
            raise ValueError("concurrency is a chat knob")
        return self._set(job, concurrency=int(n))

    def set_max_tokens(self, n: int) -> dict:
        return self._set("chat", max_tokens=int(n))

    def set_threads(self, job: str, n: int) -> dict:
        return self._set(job, threads=int(n))

    def set_device(self, job: str, device: str) -> dict:
        if device not in ("gpu", "cpu"):
            raise ValueError(device)
        return self._set(job, device=device)

    @staticmethod
    def status(job: str) -> dict:
        return read_json(status_path(job))

    def wait_for(self, job: str, pred, timeout: float = 120) -> dict:
        t = time.time()
        while time.time() - t < timeout:
            s = self.status(job)
            if s and pred(s):
                return s
            time.sleep(0.25)
        raise TimeoutError(f"{job} did not reach the requested state in {timeout}s: {self.status(job)}")
