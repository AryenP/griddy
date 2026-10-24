"""Controller tests (SPEC §12): knob calls are idempotent; pause/resume round-trip on train.py
with a tiny model (test config in a temp dir; trains on the same real local text)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from core.timeline import Timeline

ROOT = Path(__file__).resolve().parents[1]


def test_knobs_idempotent(tmp_path, monkeypatch):
    import workloads.base as base
    monkeypatch.setattr(base, "CONTROL_DIR", tmp_path)
    from controller.knobs import Knobs
    tl = Timeline(run_id="k", root=tmp_path)
    k = Knobs(tl)
    k.pause("train"); k.pause("train"); k.set_device("train", "cpu"); k.set_device("train", "cpu")
    tl.close()
    actions = [e for e in Timeline.read(tmp_path / "k" / "timeline.jsonl") if e.kind == "action"]
    assert len(actions) == 2
    assert json.loads((tmp_path / "train.json").read_text()) == {"state": "pause", "device": "cpu"}


def _wait(path: Path, pred, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        try:
            s = json.loads(path.read_text())
            if pred(s):
                return s
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    raise TimeoutError(path.read_text() if path.exists() else "no status")


def test_train_pause_resume_roundtrip(tmp_path):
    pytest.importorskip("torch")          # Mac extra; CI and non-Mac machines skip this one
    cfg = yaml.safe_load((ROOT / "config" / "jobs.yaml").read_text())
    cfg["workloads"].update(control_dir=str(tmp_path / "ctl"), checkpoint_dir=str(tmp_path / "ck"))
    cfg["workloads"]["train"].update(d_model=32, n_layers=1, n_heads=2, seq_len=32, batch_size=4, checkpoint_every_steps=5)
    cdir = tmp_path / "config"; cdir.mkdir()
    (cdir / "jobs.yaml").write_text(yaml.safe_dump(cfg))
    for f in ("isos.yaml", "policy.yaml"):
        (cdir / f).write_text((ROOT / "config" / f).read_text())
    ctl, st = tmp_path / "ctl" / "train.json", tmp_path / "ctl" / "train.status.json"
    ctl.parent.mkdir()
    ctl.write_text(json.dumps({"state": "run", "device": "cpu", "threads": 2}))
    env = {**os.environ, "CONFIG_DIR": str(cdir)}
    p = subprocess.Popen([sys.executable, "-m", "workloads.train"], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait(st, lambda s: s.get("step", 0) >= 12)
        ctl.write_text(json.dumps({"state": "pause", "device": "cpu", "threads": 2}))
        paused = _wait(st, lambda s: s["state"] == "paused")
        time.sleep(0.6)
        assert json.loads(st.read_text())["step"] == paused["step"]          # really stopped
        assert json.loads((tmp_path / "ck" / "train.json").read_text())["step"] == paused["step"]  # checkpointed
        ctl.write_text(json.dumps({"state": "run", "device": "cpu", "threads": 2}))
        _wait(st, lambda s: s["state"] == "running" and s["step"] > paused["step"])
        ctl.write_text(json.dumps({"state": "stop", "device": "cpu", "threads": 2}))
        p.wait(30)
        last = json.loads((tmp_path / "ck" / "train.json").read_text())["step"]
        # a fresh process resumes from the checkpoint, not from zero
        ctl.write_text(json.dumps({"state": "run", "device": "cpu", "threads": 2}))
        p = subprocess.Popen([sys.executable, "-m", "workloads.train"], cwd=ROOT, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        s = _wait(st, lambda s: s.get("state") == "running" and s.get("pid") == p.pid)
        assert s["step"] > last
    finally:
        ctl.write_text(json.dumps({"state": "stop"}))
        try:
            p.wait(30)
        except subprocess.TimeoutExpired:
            p.kill()
