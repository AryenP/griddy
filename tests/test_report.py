"""agent/reporter.py: every Report number pinned, on the real captures and on small hand-written
timelines shaped exactly like the runtime's events (HANDOFF.md). The hand-written ones are TEST FIXTURES
(fake numbers chosen so the expected values can be worked out by hand); they live only in this file and
never reach a judge."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent import reporter
from agent.reporter import build_report
from core.types import Report

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "tests" / "fixtures" / "real_timeline_calibrate_20261023.jsonl"
REAL_SOLVE = ROOT / "tests" / "fixtures" / "real_timeline_solve_20261023.jsonl"
T0 = 1792822000.0  # Fri 23 Oct 2026, before train's Mon 26 Oct deadline in config/jobs.yaml


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def _write(tmp_path: Path, events: list[tuple[float, str, dict]], name: str = "run-test") -> Path:
    d = tmp_path / name
    d.mkdir()
    p = d / "timeline.jsonl"
    p.write_text("".join(json.dumps({"t": t, "kind": k, "data": data}) + "\n" for t, k, data in events))
    return p


def _power(t: float, w: float) -> tuple[float, str, dict]:
    return (t, "power", {"source": "powermetrics", "t": t, "cpu_w": w, "gpu_w": 0.0, "ane_w": 0.0,
                         "combined_w": w, "fields": ["ane", "combined", "cpu", "gpu"]})


def _grid(t: float, price: float, carbon: float) -> tuple[float, str, dict]:
    return (t, "grid", {"feed": "signal", "iso": "CAISO", "location": "TH_SP15_GEN-APND", "t": t,
                        "price_now": price, "price_interval_start": _iso(t), "carbon_now": carbon})


def _chat(t: float, ttft: float | None, total: float | None) -> tuple[float, str, dict]:
    return (t, "state", {"job": "chat", "state": "running", "device": "gpu", "concurrency": 4,
                         "ttft_p95_60s": ttft, "p95_60s": total, "n_60s": 9, "t": t})


def _event_run(tmp_path, *, quiet_w=5.0) -> Path:
    """60 s at 20 W, then a 30-s cap of 10 W (50 % of the measured baseline, resolved by the executor):
    5 s more at 20 W, then quiet_w."""
    ask = {"id": "ask-1", "t": T0 + 61, "job_id": "train", "owner": "ml-team",
           "shortfall": {"kind": "deadline", "job_id": "train", "amount": 30, "message": "train slips 30 min"},
           "message": "May train finish 30 min late?", "status": "pending"}
    ev = [(T0 - 5, "note", {"msg": "runtime start", "dispatcher_enabled": True}),
          _grid(T0, 50.0, 200.0), _grid(T0 + 75, 100.0, 200.0),
          (T0 + 2, "grid", {"feed": "system_conditions", "iso": "CAISO"}),      # no price: never priced
          (T0 + 58, "event", {"intake": {"kind": "cap_event"}, "who": "utility"}),  # parsed request: not a cap
          (T0 + 59, "note", {"msg": "cap 50.0% of measured baseline 20.00 W -> 10.00 W"}),
          (T0 + 59, "event", {"id": "cap-1", "source": "text", "start": _iso(T0 + 60), "duration_s": 30,
                              "target_w": 10.0, "target_pct": 50.0, "reason": "CAISO Flex Alert", "raw": ""})]
    ev += [_power(T0 + i, 20.0) for i in range(65)]
    ev += [_power(T0 + i, quiet_w) for i in range(65, 90)]
    ev += [_chat(T0 + 50, 0.21, 6.0), _chat(T0 + 55, None, None),
           _chat(T0 + 70, 0.48, 9.5), _chat(T0 + 80, 0.30, 8.0),
           (T0 + 70, "latency", {"job": "chat", "p95_60s": 9.5, "n_60s": 9}),
           (T0 + 61, "shortfall", {"schedule_id": "sched-1", "shortfall_kind": "deadline", "job_id": "train",
                                   "amount": 30, "message": "train slips 30 min"}),
           (T0 + 66, "shortfall", {"schedule_id": "sched-2", "shortfall_kind": "deadline", "job_id": "train",
                                   "amount": 30, "message": "train slips 30 min"}),     # re-solve repeats it
           (T0 + 61, "approval", {**ask, "schedule_id": "sched-1"}),
           (T0 + 62, "approval", {"request_id": "ask-1", "who": "ml-team",
                                  "decision": {"request_id": "ask-1", "decision": "approve",
                                               "reason": "ok till Monday", "raw": "yes, ok till Monday"}}),
           (T0 + 62, "approval", {**ask, "status": "approved", "who": "ml-team", "decided_t": T0 + 62}),
           (T0 + 85, "state", {"job": "train", "state": "done", "device": "gpu", "t": T0 + 85})]
    return _write(tmp_path, ev)


def test_real_calibrate_capture_reports_whole_run():
    r = build_report(REAL)
    assert isinstance(r, Report)
    assert r.run_id == "real_timeline_calibrate_20261023"
    assert r.window_start == pytest.approx(1792822319.528203)
    assert r.window_end == pytest.approx(1792822520.3801951)
    assert r.event_w == pytest.approx(15.40513)
    assert r.energy_wh == pytest.approx(0.8618951, rel=1e-6)
    assert r.baseline_w is None and r.reduction_pct is None and r.time_to_compliance_s is None
    assert r.cost_usd == 0 and r.co2_g == 0          # the calibrate run logged no grid signal
    assert any("no cap event" in s for s in r.shortfalls)
    assert any("no live price" in s for s in r.shortfalls)


def test_real_solve_capture_without_power_does_not_crash():
    r = build_report(REAL_SOLVE)
    assert r.energy_wh == 0 and r.event_w is None
    assert any("no power samples" in s for s in r.shortfalls)


def test_event_numbers(tmp_path):
    r = build_report(_event_run(tmp_path))
    assert (r.window_start, r.window_end) == (T0 + 60, T0 + 89)   # ends at the last sample
    assert r.baseline_w == pytest.approx(20.0)
    assert r.event_w == pytest.approx((5 * 20 + 25 * 5) / 30)      # 7.5 W
    assert r.reduction_pct == pytest.approx(62.5)
    # cap 10 W; trailing 10-s mean first <= 10 W once 7 of the 10 samples are 5 W: t = 71
    assert r.time_to_compliance_s == pytest.approx(11.0)
    ws = 4 * 20 + 12.5 + 24 * 5                                     # W*s over [60, 89]
    assert r.energy_wh == pytest.approx(ws / 3600)
    # intervals starting before t=75 at $50/MWh, the 14 after at $100/MWh
    assert r.cost_usd == pytest.approx(((ws - 70) * 50 + 70 * 100) / 3600 / 1e6)
    assert r.co2_g == pytest.approx(ws / 3600 / 1000 * 200)
    # time to first token, not total latency: last before the window, worst in it; nulls skipped
    assert (r.chat_p95_before_s, r.chat_p95_during_s) == (0.21, 0.48)
    assert r.deadlines == {"train": True}
    assert r.approvals == [{"id": "ask-1", "when": T0 + 61, "what": "train", "owner": "ml-team",
                            "message": "May train finish 30 min late?", "who": "ml-team", "reply": "approve",
                            "reason": "ok till Monday", "new_deadline": None, "replied_t": T0 + 62,
                            "decision": "approved", "decided_t": T0 + 62}]
    assert r.shortfalls == ["train slips 30 min"]                   # deduplicated across re-solves


def test_intake_event_alone_is_not_a_cap(tmp_path):
    p = _write(tmp_path, [(T0, "event", {"intake": {"kind": "clarify"}, "who": "ops"}),
                          _power(T0, 3.0), _power(T0 + 1, 3.0)])
    r = build_report(p)
    assert r.baseline_w is None and r.time_to_compliance_s is None
    assert (r.window_start, r.window_end) == (T0, T0 + 1)


def test_job_change_moves_the_deadline(tmp_path):
    p = _write(tmp_path, [_power(T0, 3.0), _power(T0 + 1, 3.0),
                          (T0, "policy", {"reason": "job change", "job": "train",
                                          "changes": {"deadline": _iso(T0 + 0.5)}})])
    assert build_report(p).deadlines == {"train": False}            # due mid-run, not done


def test_cap_never_met_is_a_shortfall(tmp_path):
    r = build_report(_event_run(tmp_path, quiet_w=15.0))
    assert r.time_to_compliance_s is None
    assert any("never reached the 10.00 W cap" in s for s in r.shortfalls)


def test_meter_gaps_are_not_integrated(tmp_path):
    p = _write(tmp_path, [_power(T0, 10.0), _power(T0 + 1, 10.0), _power(T0 + 31, 10.0), _power(T0 + 32, 10.0)])
    r = build_report(p)
    assert r.energy_wh == pytest.approx(20 / 3600)
    assert any("meter gaps totalling 30 s" in s for s in r.shortfalls)


def test_torn_last_line_of_a_live_run_is_skipped(tmp_path):
    p = _write(tmp_path, [_power(T0, 10.0), _power(T0 + 1, 10.0)])
    with open(p, "a") as fh:
        fh.write('{"t": 1792822002.0, "kind": "pow')
    assert build_report(p).energy_wh == pytest.approx(10 / 3600)


def test_explicit_window_before_the_cap(tmp_path):
    r = build_report(_event_run(tmp_path), window=(T0, T0 + 10))
    assert r.event_w == pytest.approx(20.0)
    assert r.energy_wh == pytest.approx(200 / 3600)
    assert r.baseline_w is None and r.time_to_compliance_s is None   # the window is not inside the cap


def test_cli_writes_markdown_and_chart(tmp_path):
    out = tmp_path / "reports"
    assert reporter.main(["--run", str(_event_run(tmp_path)), "--out", str(out)]) == 0
    md = (out / "run-test.md").read_text(encoding="utf-8")
    assert "| Reduction | 62.5 % |" in md
    assert "time-to-first-token p95, trailing 60 s (SLA 1 s)" in md and "0.21 s / 0.48 s" in md
    assert "total-latency p95" in md and "6.00 s / 9.50 s" in md
    assert "asked ml-team about train: approved; ml-team replied approve (\"ok till Monday\")" in md
    assert (out / "run-test-power.png").stat().st_size > 0


def test_runtime_runs_and_newest(tmp_path):
    for name, on, t in (("a", True, T0), ("b-baseline", False, T0 + 10), ("c", True, T0 + 20)):
        _write(tmp_path, [(t, "note", {"msg": "runtime start", "dispatcher_enabled": on}), _power(t, 1.0)], name)
    _write(tmp_path, [_power(T0 + 30, 1.0)], "d-calibrate")                 # not a runtime run
    assert [r["run_id"] for r in reporter.runtime_runs(tmp_path)] == ["a", "b-baseline", "c"]
    assert reporter.newest(True, tmp_path).parent.name == "c"
    assert reporter.newest(False, tmp_path).parent.name == "b-baseline"
    assert reporter.resolve("c", tmp_path) == ((tmp_path / "c" / "timeline.jsonl").resolve(), "c")


def _tl(tmp_path, events, policy):
    """TEST FIXTURE: a tiny hand-written timeline (not a measurement) to pin the arithmetic."""
    import json
    d = tmp_path / f"run-{policy}"
    d.mkdir()
    lines = [{"t": 0.0, "kind": "note", "data": {"msg": "runtime start", "dispatcher_enabled": policy == "dispatcher",
                                                "policy": policy}}] + events
    (d / "timeline.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return d / "timeline.jsonl"


def _st(t, job, **kw):
    return {"t": t, "kind": "state", "data": {"job": job, "state": "running", "device": "gpu", **kw}}


def test_work_done_counts_progress_inside_the_window(tmp_path):
    from agent.reporter import Run, work_done
    p = _tl(tmp_path, [_st(5, "train", step=100, rate=10.0), _st(15, "train", step=200, rate=10.0),
                       _st(25, "train", step=300, rate=10.0)], "baseline")
    assert work_done(Run.load(p), 10, 25) == {"train": 200.0}


def test_pause_all_deadline_is_projected_from_its_own_policy(tmp_path, monkeypatch):
    from agent import reporter
    from agent.reporter import Run, deadlines
    monkeypatch.setattr(reporter.config, "jobs", {"jobs": [{"id": "train", "target_steps": 1000, "deadline": None}]})
    cap = {"t": 1.0, "kind": "event", "data": {"id": "cap-x", "start": "1970-01-01T00:00:10+00:00",
                                                "duration_s": 100, "target_w": 5.0, "source": "ui"}}
    job = {"t": 2.0, "kind": "policy", "data": {"reason": "job change", "job": "train",
                                                 "changes": {"deadline": "1970-01-01T00:02:30+00:00"}}}
    ev = [cap, job, _st(5, "train", step=400, rate=10.0), _st(20, "train", step=400, rate=10.0, state="paused")]
    paused = Run.load(_tl(tmp_path, ev + [{"t": 30, "kind": "power", "data": {"t": 30, "combined_w": 2.0}}], "pause_all"))
    met, why = deadlines(paused, 30)["train"]
    # paused until the cap ends at 110 s, then 600 steps at 10/s -> 170 s > due 150 s
    assert met is False and "projected" in why


def test_job_finished_before_the_window_is_called_out(tmp_path):
    import json as _json

    from agent.reporter import build_report
    ev = [{"t": 0.0, "kind": "note", "data": {"msg": "runtime start", "dispatcher_enabled": False}},
          {"t": 1.0, "kind": "state", "data": {"job": "batch", "state": "running", "items_done": 10}},
          {"t": 5.0, "kind": "state", "data": {"job": "batch", "state": "done", "items_done": 100}}]
    ev += [{"t": float(t), "kind": "power", "data": {"t": float(t), "combined_w": 3.0}} for t in range(0, 30)]
    p = tmp_path / "timeline.jsonl"
    p.write_text("".join(_json.dumps(e) + "\n" for e in sorted(ev, key=lambda e: e["t"])))
    r = build_report(p, window=(10.0, 29.0))
    assert r.work_done.get("batch") == 0
    assert any("batch had already finished" in m and "0 by construction" in m for m in r.shortfalls)
    assert not any("already finished" in m for m in build_report(p, window=(0.0, 29.0)).shortfalls)


def test_fleet_seconds_are_judged_on_the_fleet_total(tmp_path):
    import json as _json

    from agent.reporter import Run
    ev = [{"t": 0.0, "kind": "note", "data": {"msg": "runtime start", "dispatcher_enabled": True}}]
    for t in range(5):
        ev.append({"t": t + 0.1, "kind": "power", "data": {"t": float(t), "combined_w": 10.0}})
        if t >= 2:   # a laptop online from the third second on
            ev.append({"t": t + 0.2, "kind": "fleet_power", "data": {"t": float(t), "mac_w": 10.0,
                                                                     "sites": {"surface1": 6.0}, "combined_w": 16.0}})
    p = tmp_path / "timeline.jsonl"
    p.write_text("".join(_json.dumps(e) + "\n" for e in ev))
    assert [w for _, w in Run.load(p).power] == [10.0, 10.0, 16.0, 16.0, 16.0]


def test_withdrawn_cap_and_fleet_changes_are_in_the_report(tmp_path):
    import json as _json

    from agent.reporter import Run, build_report
    ev = [{"t": 0.0, "kind": "note", "data": {"msg": "runtime start", "dispatcher_enabled": True}},
          {"t": 1.0, "kind": "event", "data": {"id": "cap-x", "source": "simulated", "start": 10.0, "duration_s": 600,
                                               "target_w": 5.0}},
          {"t": 30.0, "kind": "note", "data": {"msg": "re-solve: fleet lap1 left during a cap", "trigger": "fleet"}},
          {"t": 40.5, "kind": "note", "data": {"msg": "cap cap-x withdrawn: test", "cap_withdrawn": "cap-x"}}]
    ev += [{"t": float(t), "kind": "power", "data": {"t": float(t), "combined_w": 4.0}} for t in range(0, 60)]
    p = tmp_path / "timeline.jsonl"
    p.write_text("".join(_json.dumps(e) + "\n" for e in sorted(ev, key=lambda e: e["t"])))
    assert Run.load(p).event_window() == (10.0, 40.5)
    r = build_report(p)
    assert any("fleet changed" in m for m in r.shortfalls)


def test_repeated_shortfalls_show_the_worst_once_and_outside_load_is_a_caveat(tmp_path):
    """Krish 14:22 (run 20261024-140239): 12 re-solves logged the same cap shortfall with different amounts, and the
    report never said the dispatcher had counted 6-12 W of load outside the plan. TEST FIXTURE timeline."""
    ev = [(T0 - 5, "note", {"msg": "runtime start", "dispatcher_enabled": True}),
          (T0 + 59, "event", {"id": "cap-1", "source": "ui", "start": _iso(T0 + 60), "duration_s": 30,
                              "target_w": 10.0, "reason": "test", "raw": ""})]
    ev += [_power(T0 + i, 20.0 if i < 60 else 9.0) for i in range(90)]
    for i, amount in enumerate([10.13, 16.44, 12.0]):
        ev.append((T0 + 61 + i, "shortfall", {"shortfall_kind": "cap", "amount": amount,
                                              "message": f"keeping every deadline, power exceeds the cap by up to {amount:.2f} W"}))
    ev += [(T0 + 70, "note", {"msg": "re-solve: load outside the plan 0.00 -> 8.20 W under the cap", "trigger": "background",
                              "background_w": 8.2}),
           (T0 + 80, "note", {"msg": "re-solve: load outside the plan 8.20 -> 11.55 W under the cap", "trigger": "background",
                              "background_w": 11.55})]
    rep = build_report(_write(tmp_path, ev))
    caps = [s for s in rep.shortfalls if "exceeds the cap" in s]
    assert caps == ["keeping every deadline, power exceeds the cap by up to 16.44 W"]
    assert any("load outside the plan up to 11.55 W was measured and counted against the cap (2 re-solve(s)" in s
               for s in rep.shortfalls)
