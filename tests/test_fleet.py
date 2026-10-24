"""The fleet: laptops as extra, measured sites (fleet/hub.py on the Mac, fleet/agent.py on each laptop).
Test doubles here are labelled: a heartbeat dict stands in for a laptop's battery reading."""
import time

import pytest

import controller.execute as ex
import workloads.base as base
from controller.knobs import Knobs
from core.timeline import Timeline
from core.types import CapEvent, PowerReading
from fleet.hub import Fleet
from tests.test_dispatcher import CAL, POLICY, SLOTS, jobs, signal

CFG = {"sites": [{"id": "surface1", "name": "Surface Pro 11", "owner": "krish"}], "stale_s": 5,
       "job": {"kind": "droppable", "owner": "data-eng", "priority": 3, "backlog_mb": 3000}}
LAPTOP_CAL = {"idle_w": 4.0, "delta_w": 9.0, "rate_mb_s": 2.0, "samples": [30, 30], "window_s": 30, "threads": 8,
              "measured_at": 0.0, "machine": "test-fixture laptop", "meter": "test fixture"}


def fleet(tmp_path, cfg=CFG) -> Fleet:
    return Fleet(Timeline(run_id="f", root=tmp_path), cfg=cfg, cal_path=tmp_path / "fleet-cal.json")


def test_no_laptops_changes_nothing(tmp_path):
    f = fleet(tmp_path, cfg={})
    r = PowerReading(t=time.time(), combined_w=12.0)
    assert f.combine(r) is r and f.jobs() == [] and f.calibration(CAL) is CAL and f.online() == []


def test_a_laptop_counts_only_when_calibrated_and_fresh(tmp_path):
    f = fleet(tmp_path)
    now = time.time()
    f.beat("surface1", {"watts": 6.5, "done_mb": 100.0}, now=now)
    assert f.online(now) == []                                   # not calibrated on itself yet
    assert f.status(now)[0]["status"].startswith("not calibrated")
    f.calibrate("surface1", LAPTOP_CAL)
    assert f.online(now) == ["surface1"] and f.membership_changed(now) == "surface1 joined"
    assert f.membership_changed(now) is None
    assert f.online(now + 6) == [] and "no heartbeat" in f.status(now + 6)[0]["status"]   # stale after 5 s
    f.beat("surface1", {"watts": None, "meter_note": "plugged in"}, now=now + 7)
    assert f.online(now + 7) == [] and f.status(now + 7)[0]["status"] == "plugged in"     # plugged in: no watts


def test_combine_adds_fresh_laptop_watts_and_logs_them(tmp_path):
    f = fleet(tmp_path)
    f.calibrate("surface1", LAPTOP_CAL)
    now = time.time()
    f.beat("surface1", {"watts": 6.5}, now=now)
    r = f.combine(PowerReading(t=now, combined_w=12.0))
    assert r.combined_w == pytest.approx(18.5)
    f.tl.close()
    import json
    events = [json.loads(e) for e in f.tl.path.read_text().splitlines() if '"fleet_power"' in e]
    assert len(events) == 1 and events[0]["data"]["mac_w"] == 12.0 and events[0]["data"]["sites"] == {"surface1": 6.5}


def test_laptop_job_and_calibration_for_the_solver(tmp_path):
    f = fleet(tmp_path)
    f.calibrate("surface1", LAPTOP_CAL)
    f.beat("surface1", {"watts": 5.0, "done_mb": 1200.0})
    (j,) = f.jobs()
    assert j.id == "surface1" and j.device == "cpu" and j.required_runtime_min == 15   # 1800 MB / 2 MB/s
    cal = f.calibration(CAL)
    assert cal.idle_w == pytest.approx(CAL.idle_w + 4.0) and cal.jobs["surface1"]["cpu"].delta_w == 9.0
    assert CAL.jobs.get("surface1") is None                    # the Mac's own calibration is untouched


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "CONTROL_DIR", tmp_path / "ctl")
    clock = {"t": SLOTS[0].timestamp() + 30}
    monkeypatch.setattr(ex.time, "time", lambda: clock["t"])
    monkeypatch.setattr(ex, "load_jobs", lambda cal: [j for j in jobs() if j.id != "batch"])
    monkeypatch.setattr(ex.Executor, "chat_busy", staticmethod(lambda: None))
    tl = Timeline(run_id="x", root=tmp_path)
    e = ex.Executor(tl, Knobs(tl), CAL, POLICY)
    f = Fleet(tl, cfg=CFG, cal_path=tmp_path / "fleet-cal.json")
    e.fleet = f
    return e, f, clock


async def test_the_plan_runs_a_laptop_and_the_cap_counts_it(rig):
    e, f, clock = rig
    f.calibrate("surface1", LAPTOP_CAL)
    f.beat("surface1", {"watts": 5.0, "done_mb": 0.0}, now=clock["t"])
    prices = [5.0] * 4 + [50.0] * 92
    s = await e.on_signal(signal(prices)) or e.schedule
    assert "surface1" in s.assignments and any(a.run for a in s.assignments["surface1"][:4])
    assert f.run["surface1"] is True                           # cheap slot: the laptop runs
    # a cap that fits the Mac's idle + chat + the laptop's idle, but not the laptop's job too
    s = await e.add_event(CapEvent(source="ui", start=SLOTS[0], duration_s=3600, target_w=1 + 8 + 4 + 2))
    assert not any(a.run for a in s.assignments["surface1"][:4]) and f.run["surface1"] is False
    assert all(w <= 15 + 1e-6 for w in s.planned_w[:4])


async def test_a_laptop_that_leaves_is_paused_and_replanned(rig):
    e, f, clock = rig
    f.calibrate("surface1", LAPTOP_CAL)
    f.beat("surface1", {"watts": 5.0, "done_mb": 0.0}, now=clock["t"])
    await e.on_signal(signal([5.0] * 4 + [50.0] * 92))
    assert f.membership_changed(clock["t"]) == "surface1 joined"
    clock["t"] += 10                                            # no heartbeat for 10 s
    assert f.membership_changed(clock["t"]) == "surface1 left"
    s = await e.resolve("fleet: surface1 left")
    assert "surface1" not in s.assignments and f.run["surface1"] is False


def test_the_laptop_job_compresses_only_while_told_to(tmp_path, monkeypatch):
    from fleet import agent
    monkeypatch.setattr(agent, "STATE_DIR", tmp_path)
    job = agent.CompressJob("t1", threads=2)
    time.sleep(0.3)
    assert job.done_mb == 0.0                                  # starts paused
    job.running.set()
    deadline = time.time() + 20
    while job.done_mb < 2 and time.time() < deadline:
        time.sleep(0.1)
    job.running.clear()
    assert job.done_mb >= 2                                    # real lzma work on the standard library
    time.sleep(1.5)
    settled = job.done_mb
    time.sleep(1.0)
    assert job.done_mb == settled                              # paused: no more work
    job.save()
    assert agent.CompressJob("t1", threads=1).done_mb == pytest.approx(settled)   # progress survives a restart


def test_site_routes(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes import make_router

    class Rt:
        fleet = fleet(tmp_path)
    app = FastAPI()
    app.include_router(make_router(Rt()))
    c = TestClient(app)
    assert c.post("/api/sites/nope/beat", json={"watts": 3.0}).status_code == 404
    assert c.post("/api/sites/surface1/beat", json={"watts": 3.0, "done_mb": 1.0}).json() == {"site": "surface1", "run": False}
    assert c.post("/api/sites/surface1/beat", json={"watts": -1}).status_code == 422
    assert c.post("/api/sites/surface1/calibration", json={**LAPTOP_CAL, "rate_mb_s": 0}).status_code == 422
    assert c.post("/api/sites/surface1/calibration", json=LAPTOP_CAL).json()["status"] == "stored"
    assert Rt.fleet.online() == ["surface1"]


async def test_the_mac_waits_for_slow_laptop_meters(rig):
    e, f, clock = rig
    f.meter_lag_s = 75.0
    assert e.meter_lag_s() == 0.0                              # no laptop online: the Mac's own timing
    f.calibrate("surface1", LAPTOP_CAL)
    f.beat("surface1", {"watts": 5.0, "done_mb": 0.0}, now=clock["t"])
    assert e.meter_lag_s() == 75.0
    e.policy = e.policy.model_copy(update={"replan": {"background_window_s": 20, "settle_s": 5, "background_delta_w": 0.5}})
    await e.on_signal(signal([5.0] * 4 + [50.0] * 92))
    await e.add_event(CapEvent(source="ui", start=SLOTS[0], duration_s=3600, target_w=30.0))
    for _ in range(60):                                        # 60 s of measured watts well above the plan
        clock["t"] += 1
        f.beat("surface1", {"watts": 5.0, "done_mb": 0.0}, now=clock["t"])
        e.on_power(PowerReading(t=clock["t"], combined_w=e.plan.planned_w + 6))
    assert e.background_drift() is None                        # 25 s + 75 s of lag have not passed yet
    for _ in range(45):
        clock["t"] += 1
        f.beat("surface1", {"watts": 5.0, "done_mb": 0.0}, now=clock["t"])
        e.on_power(PowerReading(t=clock["t"], combined_w=e.plan.planned_w + 6))
    assert e.background_drift() == pytest.approx(6.0, abs=0.1)


def test_site_routes_need_the_token_when_one_is_set(tmp_path, monkeypatch):
    # Krish K1 #4: with FLEET_TOKEN set, a phone on the venue network cannot post a laptop's watts
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes import make_router
    from core.config import settings
    monkeypatch.setattr(settings, "fleet_token", "s3cret-for-test")

    class Rt:
        fleet = fleet(tmp_path)
    app = FastAPI()
    app.include_router(make_router(Rt()))
    c = TestClient(app)
    assert c.post("/api/sites/surface1/beat", json={"watts": 3.0}).status_code == 401
    assert c.post("/api/sites/surface1/beat", json={"watts": 3.0}, headers={"X-Brownout-Fleet-Token": "nope"}).status_code == 401
    ok = c.post("/api/sites/surface1/beat", json={"watts": 3.0}, headers={"X-Brownout-Fleet-Token": "s3cret-for-test"})
    assert ok.status_code == 200
    assert c.post("/api/sites/surface1/calibration", json=LAPTOP_CAL).status_code == 401
