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


async def test_traffic_drift_triggers_resolve_rate_limited(rig, monkeypatch):
    e, clock, tmp = rig
    e.policy = e.policy.model_copy(update={"replan": {"chat_busy_delta": 0.5, "min_interval_s": 60}})
    busy = {"v": 0.0}
    monkeypatch.setattr(ex.Executor, "chat_busy", staticmethod(lambda: busy["v"]))
    await e.on_signal(signal([50.0] * 96))
    assert e.schedule.chat_busy_streams == 0.0
    busy["v"] = 2.0
    assert e.drift_reason() is None                    # within min_interval_s of the last solve
    clock["t"] += 61
    assert "chat traffic 0.00 -> 2.00" in e.drift_reason()
    await e.resolve("drift")
    assert e.schedule.chat_busy_streams == 2.0 and e.drift_reason() is None


async def test_load_outside_the_plan_under_a_cap_resolves(rig, monkeypatch):
    e, clock, tmp = rig
    e.policy = e.policy.model_copy(update={"replan": {
        "background_window_s": 20, "settle_s": 5, "background_delta_w": 0.5, "chat_busy_delta": 0.5}})
    monkeypatch.setattr(ex.Executor, "chat_busy", staticmethod(lambda: None))
    monkeypatch.setattr(ex, "load_jobs", lambda cal: [j for j in jobs() if j.id != "batch"])
    await e.on_signal(signal([5.0] * 4 + [50.0] * 92))
    await e.add_event(CapEvent(source="ui", start=SLOTS[0], duration_s=3600, target_w=15.5))
    assert ctl(tmp, "train")["state"] == "run" and ctl(tmp, "train")["device"] == "cpu"
    assert e.plan.planned_w == pytest.approx(15.0)

    def meter(w, seconds):
        for _ in range(seconds):
            clock["t"] += 1
            e.on_power(PowerReading(t=clock["t"], combined_w=w))

    meter(15.0, 10)
    assert e.background_drift() is None              # the plan has not run a settled window yet
    meter(15.0, 20)
    assert e.background_drift() is None              # measured matches the plan
    meter(16.2, 20)                                  # 1.2 W nobody planned appears
    bg = e.background_drift()
    assert bg == pytest.approx(1.2, abs=0.05)
    e.background_w = bg
    s = await e.resolve("drift: background")
    assert s.background_w == pytest.approx(bg) and ctl(tmp, "train")["state"] == "pause"
    assert e.plan.planned_w == pytest.approx(9.0 + bg)
    assert e.background_drift() is None              # just re-solved: settle first
    meter(9.0 + bg, 30)                              # idle + chat as planned, plus the same outside load
    assert e.background_drift() is None
    meter(9.0, 30)                                   # the outside load goes away: re-solve so train can run
    assert e.background_drift() == pytest.approx(0.0)


async def test_no_background_resolve_without_a_cap(rig, monkeypatch):
    e, clock, _ = rig
    e.policy = e.policy.model_copy(update={"replan": {"background_window_s": 20, "settle_s": 5, "background_delta_w": 0.5}})
    monkeypatch.setattr(ex.Executor, "chat_busy", staticmethod(lambda: None))
    await e.on_signal(signal([50.0] * 96))
    for _ in range(40):
        clock["t"] += 1
        e.on_power(PowerReading(t=clock["t"], combined_w=40.0))
    assert e.background_drift() is None


async def test_idle_floor_is_remeasured_in_place_when_only_idle_runs(rig, monkeypatch):
    # a 9 W calibrated idle prices any training over a 14.5 W cap; the measured 0.5 W idle fits GPU training (12 W)
    e, clock, tmp = rig
    e.policy = e.policy.model_copy(update={"replan": {
        "background_window_s": 20, "settle_s": 5, "background_delta_w": 0.5, "chat_busy_delta": 0.5, "idle_busy_max": 0.05}})
    monkeypatch.setattr(ex.Executor, "chat_busy", staticmethod(lambda: 0.0))
    monkeypatch.setattr(ex, "load_jobs", lambda cal: [j for j in jobs() if j.id != "batch"])
    e.cal = e.cal.model_copy(update={"idle_w": 9.0})          # a calibration taken while something else ran
    await e.on_signal(signal([5.0] * 4 + [50.0] * 92))
    await e.add_event(CapEvent(source="ui", start=SLOTS[0], duration_s=3600, target_w=14.5))
    assert ctl(tmp, "train")["state"] == "pause"              # 9 + 6 > 14.5 on the calibrated idle
    for _ in range(30):
        clock["t"] += 1
        e.on_power(PowerReading(t=clock["t"], combined_w=0.5))
    idle = e.idle_drift()
    assert idle == pytest.approx(0.5)
    e.cal = e.cal.model_copy(update={"idle_w": idle})
    await e.resolve("drift: idle")
    assert ctl(tmp, "train")["state"] == "run" and e.plan.planned_w <= 14.5   # 0.5 + 12 W on the GPU fits
    for _ in range(30):
        clock["t"] += 1
        e.on_power(PowerReading(t=clock["t"], combined_w=12.6))
    assert e.idle_drift() is None                             # a job is running: idle is not measurable


async def test_idle_floor_never_rises_and_needs_quiet_chat(rig, monkeypatch):
    e, clock, _ = rig
    e.policy = e.policy.model_copy(update={"replan": {"background_window_s": 20, "settle_s": 5,
                                                      "background_delta_w": 0.5, "idle_busy_max": 0.05}})
    busy = {"v": 0.0}
    monkeypatch.setattr(ex.Executor, "chat_busy", staticmethod(lambda: busy["v"]))
    monkeypatch.setattr(ex, "load_jobs", lambda cal: [j for j in jobs() if j.id != "batch"])
    await e.on_signal(signal([5.0] * 4 + [50.0] * 92))
    await e.add_event(CapEvent(source="ui", start=SLOTS[0], duration_s=3600, target_w=1.2))   # nothing fits
    for _ in range(30):
        clock["t"] += 1
        e.on_power(PowerReading(t=clock["t"], combined_w=3.0))
    assert e.idle_drift() is None                             # above the calibrated 1 W: background, not idle
    busy["v"] = 1.0
    for _ in range(30):
        clock["t"] += 1
        e.on_power(PowerReading(t=clock["t"], combined_w=0.2))
    assert e.idle_drift() is None                             # chat has traffic: not an idle reading
