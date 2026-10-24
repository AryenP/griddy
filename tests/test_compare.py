"""scripts/compare.py on two hand-written runs. TEST FIXTURES: the watts and prices below are made up
so the expected numbers can be worked out by hand; they live only in this file."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("compare", ROOT / "scripts" / "compare.py")
compare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare)

T0 = 1792822000.0


def _run(root: Path, run_id: str, mode: str, watts: list[float], event: dict | None) -> Path:
    d = root / run_id
    d.mkdir(parents=True)
    ev = [{"t": T0, "kind": "grid", "data": {"price_now": 40.0, "carbon_now": 250.0}},
          {"t": T0, "kind": "plan", "data": {"mode": mode, "actions": []}}]
    ev += [{"t": T0 + i, "kind": "power", "data": {"t": T0 + i, "combined_w": w}} for i, w in enumerate(watts)]
    if event:
        ev.append({"t": T0, "kind": "event", "data": event})
    p = d / "timeline.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in ev))
    return p


@pytest.fixture
def runs(tmp_path):
    cap = {"source": "ui", "start": datetime.fromtimestamp(T0, tz=timezone.utc).isoformat(),
           "duration_s": 20, "target_w": 10.0, "reason": "test"}
    d = _run(tmp_path, "run-d", "dispatcher", [20.0] * 4 + [8.0] * 17, cap)       # 21 samples, t0..t20
    b = _run(tmp_path, "run-b", "baseline", [20.0] * 31, None)                   # 31 samples, t0..t30
    return tmp_path, d, b


def test_newest_picks_by_plan_mode(runs):
    root, d, b = runs
    assert compare.newest("dispatcher", root) == d
    assert compare.newest("baseline", root) == b


def test_same_window_length_and_numbers(runs):
    _, d, b = runs
    rows, span = compare.compare(d, b)
    assert span == 20                                       # the shorter run, t0..t20
    (_, rd, repd, capd), (_, rb, repb, capb) = rows
    assert capd == capb == 10.0                             # baseline logged no event: dispatched cap
    ws_d = 3 * 20 + 14 + 16 * 8                             # trapezoids over 20 s
    ws_b = 20 * 20
    assert repd.energy_wh == pytest.approx(ws_d / 3600)
    assert repb.energy_wh == pytest.approx(ws_b / 3600)
    assert repb.cost_usd - repd.cost_usd == pytest.approx((ws_b - ws_d) / 3600 / 1e6 * 40)
    assert repb.co2_g - repd.co2_g == pytest.approx((ws_b - ws_d) / 3600 / 1000 * 250)
    assert compare.share_under(rd, repd.window_start, repd.window_end, capd) == pytest.approx(17 / 21)
    assert compare.share_under(rb, repb.window_start, repb.window_end, capb) == 0
    assert repd.baseline_w is None                          # no samples before the event
    assert repd.time_to_compliance_s == 12                  # t3..t12 = 1*20 + 9*8 = 9.2 W: 10-s mean first <= 10 W at t12
    assert repb.time_to_compliance_s is None


def test_cli_writes_table_and_chart(runs, tmp_path):
    _, d, b = runs
    out = tmp_path / "reports"
    assert compare.main(["--dispatched", str(d), "--baseline", str(b), "--out", str(out)]) == 0
    md = (out / "compare-run-d-vs-run-b.md").read_text(encoding="utf-8")
    assert "| Seconds at or under cap | 81 % | 0 % | |" in md
    assert (out / "compare-run-d-vs-run-b.png").stat().st_size > 0
