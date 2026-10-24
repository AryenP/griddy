"""HTTP contract tests (HANDOFF.md). TEST FIXTURE: a stand-in runtime that records what the routes
hand it; the real Runtime needs powermetrics and runs only on the demo Mac."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import make_router
from dispatcher.solve import solve
from tests.test_dispatcher import CAL, POLICY, jobs, signal


class FakeExecutor:
    def __init__(self):
        self.calls, self.dispatcher_enabled, self.schedule = [], True, None

    def jobs(self):
        return jobs()

    async def set_policy(self, **c):
        self.calls.append(("policy", c))
        return solve(signal([50.0] * 96), jobs(), POLICY, CAL)

    async def set_job(self, job_id, **c):
        self.calls.append(("job", job_id, c))
        return None

    async def add_event(self, ev):
        self.calls.append(("event", ev))
        return None

    def set_dispatcher(self, enabled):
        self.dispatcher_enabled = enabled


class FakeRuntime:
    def __init__(self):
        self.executor = FakeExecutor()

    def snapshot(self):
        return {"dispatcher_enabled": self.executor.dispatcher_enabled}


def client():
    rt = FakeRuntime()
    app = FastAPI()
    app.include_router(make_router(rt))
    return TestClient(app), rt


def test_policy_null_clears_cap_and_returns_schedule():
    c, rt = client()
    r = c.post("/api/policy", json={"power_cap_w": None})
    assert r.status_code == 200 and r.json()["solver_status"] == "OPTIMAL"
    assert rt.executor.calls == [("policy", {"power_cap_w": None})]
    assert c.post("/api/policy", json={}).status_code == 400


def test_event_needs_exactly_one_target():
    c, rt = client()
    base = {"start": "2026-10-24T00:00:00-07:00", "duration_s": 900}
    assert c.post("/api/event", json=base).status_code == 400
    assert c.post("/api/event", json={**base, "target_w": 10, "target_pct": 20}).status_code == 400
    assert c.post("/api/event", json={**base, "target_pct": 30}).status_code == 200
    ev = rt.executor.calls[-1][1]
    assert ev.target_pct == 30 and ev.source == "ui" and ev.raw


def test_jobs_route_rejects_chat_and_unknown():
    c, _ = client()
    assert c.post("/api/jobs/chat", json={"deadline": None}).status_code == 404
    assert c.post("/api/jobs/nope", json={"deadline": None}).status_code == 404
    assert c.post("/api/jobs/train", json={"deadline": "2026-10-24T02:00:00-07:00"}).status_code == 200


def test_dispatcher_toggle_and_state():
    c, _ = client()
    assert c.post("/api/dispatcher", json={"enabled": False}).json() == {"enabled": False}
    assert c.get("/api/state").json() == {"dispatcher_enabled": False}


def test_runs_lists_runtime_runs_only(tmp_path, monkeypatch):
    import json as _json

    import api.routes as routes
    for name, first in [("a", {"t": 1.0, "kind": "note", "data": {"msg": "runtime start", "dispatcher_enabled": True}}),
                        ("b-baseline", {"t": 2.0, "kind": "note", "data": {"msg": "runtime start", "dispatcher_enabled": False}}),
                        ("c-pause_all", {"t": 3.0, "kind": "note", "data": {"msg": "runtime start", "dispatcher_enabled": False,
                                                                           "policy": "pause_all", "machine": "m"}}),
                        ("d-solve", {"t": 4.0, "kind": "grid", "data": {}})]:
        (tmp_path / name).mkdir()
        (tmp_path / name / "timeline.jsonl").write_text(_json.dumps(first) + "\n")
    monkeypatch.setattr(routes, "RUNS", tmp_path)
    c, _ = client()
    got = c.get("/api/runs").json()
    assert [(r["run_id"], r["dispatcher_enabled"], r["policy"]) for r in got] == [
        ("a", True, "dispatcher"), ("b-baseline", False, "baseline"), ("c-pause_all", False, "pause_all")]
    assert got[2]["machine"] == "m" and "path" not in got[0]


def test_receipts_routes_on_real_captured_runs(tmp_path, monkeypatch):
    import shutil

    import api.routes as routes
    for name in ("real_timeline_calibrate_20261023.jsonl", "real_timeline_solve_20261023.jsonl"):
        d = tmp_path / name.split(".")[0]
        d.mkdir()
        shutil.copy(f"tests/fixtures/{name}", d / "timeline.jsonl")
    monkeypatch.setattr(routes, "RUNS", tmp_path)
    c, _ = client()
    r = c.get("/api/report", params={"run": "real_timeline_solve_20261023"})
    assert r.status_code == 200 and r.json()["run_id"]
    assert c.get("/api/report", params={"run": "nope"}).status_code == 404
    assert c.get("/api/compare").status_code == 404          # no runtime runs in this folder
    assert c.get("/api/compare", params={"baseline_policy": "pause_all"}).status_code == 404
    assert c.get("/api/compare", params={"baseline_policy": "other"}).status_code == 422
    s = c.get("/api/runs/real_timeline_calibrate_20261023/series").json()
    assert s["run_id"] == "real_timeline_calibrate_20261023" and len(s["power"]) > 10
    assert all(len(p) == 2 and p[1] >= 0 for p in s["power"]) and s["power"] == sorted(s["power"])
    assert {"caps", "actions", "shortfalls", "policy", "machine"} <= set(s)
    assert c.get("/api/runs/nope/series").status_code == 404


def test_run_routes_take_run_ids_never_paths(tmp_path, monkeypatch):
    import api.routes as routes
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"t": 1.0, "kind": "note", "data": {"msg": "runtime start"}}\n')
    (tmp_path / "runs").mkdir()
    monkeypatch.setattr(routes, "RUNS", tmp_path / "runs")
    c, _ = client()
    for bad in (str(outside), "../outside.jsonl", "..", "/etc/hosts"):
        assert c.get("/api/report", params={"run": bad}).status_code == 404, bad
        assert c.get("/api/compare", params={"dispatched": bad, "baseline": bad}).status_code == 404, bad
    assert isinstance(c.get("/api/trace").json(), list)
