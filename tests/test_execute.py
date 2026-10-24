"""Executor tests. TEST FIXTURES ONLY: calibration, jobs and prices come from tests/test_dispatcher.py
(invented for unit tests); workload control files go to a temp dir; time is moved by monkeypatch."""
import json
from datetime import timedelta

import pytest

import controller.execute as ex
import workloads.base as base
from controller.knobs import Knobs
from core.timeline import Timeline
from core.types import CapEvent, PowerReading
from tests.test_dispatcher import CAL, POLICY, SLOTS, jobs, signal


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "CONTROL_DIR", tmp_path / "ctl")
    clock = {"t": SLOTS[0].timestamp() + 30}
    monkeypatch.setattr(ex.time, "time", lambda: clock["t"])
    monkeypatch.setattr(ex, "load_jobs", lambda cal: jobs(train_deadline=SLOTS[8]))
    tl = Timeline(run_id="x", root=tmp_path)
    e = ex.Executor(tl, Knobs(tl), CAL, POLICY)
    return e, clock, tmp_path


def ctl(tmp, job):
    return json.loads((tmp / "ctl" / f"{job}.json").read_text())


async def test_follows_schedule_across_slot_boundary(rig):
    e, clock, tmp = rig
    prices = [50.0] * 96
    prices[1] = 500.0                      # slot 1 is expensive: train should sit it out
    await e.on_signal(signal(prices))
    assert e.plan.slot_index == 0
    assert ctl(tmp, "train")["state"] == "run"
    clock["t"] = SLOTS[1].timestamp() + 1  # cross the boundary, no other input
    e.tick()
    assert e.plan.slot_index == 1 and ctl(tmp, "train")["state"] == "pause"
    clock["t"] = SLOTS[2].timestamp() + 1
    e.tick()
    assert ctl(tmp, "train")["state"] == "run"
    assert ctl(tmp, "chat")["concurrency"] == 4


async def test_cap_event_pct_uses_measured_baseline(rig):
    e, clock, tmp = rig
    for k in range(60):
        e.on_power(PowerReading(t=clock["t"] - 60 + k, combined_w=40.0))
    await e.on_signal(signal([50.0] * 96))
    s = await e.add_event(CapEvent(source="ui", start=SLOTS[1], duration_s=900, target_pct=60))
    assert s.caps_w[1] == pytest.approx(16.0) and s.caps_w[0] is None
    clock["t"] = SLOTS[1].timestamp() + 1
    e.tick()
    assert e.plan.cap_w == pytest.approx(16.0)
    assert ctl(tmp, "train")["state"] == "pause"      # 1 W idle + chat + 12 W train would break 16 W
    assert any("paused in 1 capped slot" in f for f in s.explanations)


async def test_pct_event_without_baseline_is_refused(rig):
    e, _, _ = rig
    await e.on_signal(signal([50.0] * 96))
    with pytest.raises(ValueError):
        await e.add_event(CapEvent(source="ui", start=SLOTS[1], duration_s=900, target_pct=30))


async def test_dispatcher_off_runs_everything(rig):
    e, _, tmp = rig
    prices = [50.0] * 96
    prices[0] = 500.0
    await e.on_signal(signal(prices))
    assert ctl(tmp, "train")["state"] == "pause"
    e.set_dispatcher(False)
    assert e.plan.mode == "baseline"
    assert ctl(tmp, "train")["state"] == "run" and ctl(tmp, "batch")["state"] == "run"


async def test_job_change_resolves(rig):
    e, _, _ = rig
    await e.on_signal(signal([50.0] * 96))
    s = await e.set_job("train", deadline=SLOTS[0] + timedelta(hours=2, minutes=30))
    on = [i for i, a in enumerate(s.assignments["train"]) if a.run]
    assert on and max(on) < 10
