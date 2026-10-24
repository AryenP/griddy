"""agent/reporter.py: every Report number pinned, on the real calibrate capture and on small
hand-written timelines. The hand-written ones are TEST FIXTURES (fake numbers chosen so the expected
values can be worked out by hand); they live only in this file and never reach a judge."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent import reporter
from agent.reporter import build_report

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "tests" / "fixtures" / "real_timeline_calibrate_20261023.jsonl"
T0 = 1792822000.0  # Fri 23 Oct 2026, before train's Mon 26 Oct deadline in config/jobs.yaml


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def _write(tmp_path: Path, events: list[tuple[float, str, dict]]) -> Path:
    d = tmp_path / "run-test"
    d.mkdir()
    p = d / "timeline.jsonl"
    p.write_text("".join(json.dumps({"t": t, "kind": k, "data": data}) + "\n" for t, k, data in events))
    return p


def _power(t: float, w: float) -> tuple[float, str, dict]:
    return (t, "power", {"source": "powermetrics", "t": t, "combined_w": w})


def _event_run(tmp_path, *, quiet_w=5.0) -> Path:
    """60 s at 20 W, then a 30-s event at 50 % of baseline (cap 10 W): 5 s more at 20 W, then quiet_w."""
    ev = [(T0, "grid", {"feed": "signal", "price_now": 50.0, "carbon_now": 200.0}),
          (T0 + 75, "grid", {"feed": "signal", "price_now": 100.0, "carbon_now": 200.0})]
    ev += [_power(T0 + i, 20.0) for i in range(65)]
    ev += [_power(T0 + i, quiet_w) for i in range(65, 90)]
    ev += [(T0 + 60, "event", {"id": "cap-1", "source": "ui", "start": _iso(T0 + 60), "duration_s": 30,
                               "target_w": None, "target_pct": 50, "reason": "CAISO Flex Alert", "raw": ""}),
           (T0 + 50, "latency", {"p95_60s": 1.2, "n_60s": 10}),
           (T0 + 70, "latency", {"p95_60s": 3.1, "n_60s": 9}),
           (T0 + 80, "latency", {"p95_60s": 2.4, "n_60s": 9}),
           (T0 + 61, "shortfall", {"kind": "deadline", "job_id": "train", "amount": 30,
                                   "message": "train slips 30 min"}),
           (T0 + 62, "approval", {"plan_id": "plan-1", "action_rung": 1, "approver": "ml-team",
                                  "decision": "approved", "reason": "ok till Monday", "t": T0 + 62}),
           (T0 + 85, "state", {"job": "train", "state": "done", "device": "gpu", "t": T0 + 85})]
    return _write(tmp_path, ev)


def test_real_capture_without_event_reports_whole_run():
    r = build_report(REAL)
    assert r.window_start == pytest.approx(1792822319.528203)
    assert r.window_end == pytest.approx(1792822520.3801951)
    assert r.event_w == pytest.approx(15.40513)
    assert r.energy_wh == pytest.approx(0.8618951, rel=1e-6)
    assert r.baseline_w is None and r.reduction_pct is None and r.time_to_compliance_s is None
    assert r.cost_usd == 0 and r.co2_g == 0          # the calibrate run logged no grid signal
    assert any("no live price" in s for s in r.shortfalls)


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
    assert (r.chat_p95_before_s, r.chat_p95_during_s) == (1.2, 3.1)
    assert r.deadlines == {"train": True}
    assert r.approvals == [{"t": T0 + 62, "who": "ml-team", "what": "plan-1", "decision": "approved",
                            "reason": "ok till Monday"}]
    assert r.shortfalls == ["train slips 30 min"]


def test_cap_never_met_is_a_shortfall(tmp_path):
    r = build_report(_event_run(tmp_path, quiet_w=15.0))
    assert r.time_to_compliance_s is None
    assert any("never reached the 10.0 W cap" in s for s in r.shortfalls)


def test_meter_gaps_are_not_integrated(tmp_path):
    p = _write(tmp_path, [_power(T0, 10.0), _power(T0 + 1, 10.0), _power(T0 + 31, 10.0), _power(T0 + 32, 10.0)])
    r = build_report(p)
    assert r.energy_wh == pytest.approx(20 / 3600)
    assert any("meter gaps totalling 30 s" in s for s in r.shortfalls)


def test_explicit_window(tmp_path):
    r = build_report(_event_run(tmp_path), window=(T0, T0 + 10))
    assert r.event_w == pytest.approx(20.0)
    assert r.energy_wh == pytest.approx(200 / 3600)


def test_cli_writes_markdown_and_chart(tmp_path):
    out = tmp_path / "reports"
    assert reporter.main(["--run", str(_event_run(tmp_path)), "--out", str(out)]) == 0
    md = (out / "run-test.md").read_text(encoding="utf-8")
    assert "| Reduction | 62.5 % |" in md and "ml-team approved plan-1" in md
    assert (out / "run-test-power.png").stat().st_size > 0
