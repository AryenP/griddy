"""agent.reporter.compare_runs and scripts/compare.py on two hand-written runs. TEST FIXTURES: the watts
and prices below are made up so the expected numbers can be worked out by hand; they live only in this
file. Event shapes follow HANDOFF.md exactly (runtime-start note, grid feed "signal", resolved cap)."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.reporter import Run, compare_runs, newest, share_under
from core.types import Comparison

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("compare_cli", ROOT / "scripts" / "compare.py")
compare_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_cli)

T0 = 1792822000.0


def _run(root: Path, run_id: str, dispatcher: bool, watts: list[float], event: dict | None, t0=T0) -> Path:
    d = root / run_id
    d.mkdir(parents=True)
    ev = [{"t": t0 - 1, "kind": "note", "data": {"msg": "runtime start", "dispatcher_enabled": dispatcher}},
          {"t": t0, "kind": "grid", "data": {"feed": "signal", "price_now": 40.0, "carbon_now": 250.0}}]
    ev += [{"t": t0 + i, "kind": "power", "data": {"t": t0 + i, "combined_w": w}} for i, w in enumerate(watts)]
    if event:
        ev.append({"t": t0, "kind": "event", "data": event})
    p = d / "timeline.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in ev))
    return p


@pytest.fixture
def runs(tmp_path):
    cap = {"id": "cap-1", "source": "ui", "start": datetime.fromtimestamp(T0, tz=timezone.utc).isoformat(),
           "duration_s": 20, "target_w": 10.0, "target_pct": None, "reason": "test", "raw": ""}
    d = _run(tmp_path, "run-d", True, [20.0] * 4 + [8.0] * 17, cap)                # 21 samples, t0..t20
    b = _run(tmp_path, "run-b-baseline", False, [20.0] * 31, None, t0=T0 + 100)   # 31 samples, later
    return tmp_path, d, b


def test_newest_picks_by_runtime_start_note(runs):
    root, d, b = runs
    assert newest(True, root) == d
    assert newest(False, root) == b


def test_same_window_length_and_numbers(runs):
    _, d, b = runs
    c = compare_runs(d, b)
    assert isinstance(c, Comparison)
    assert c.window_s == 20                                 # the shorter run, t0..t20
    repd, repb = c.dispatched, c.baseline
    assert (repd.run_id, repb.run_id) == ("run-d", "run-b-baseline")
    assert repb.window_start == T0 + 100                    # baseline: from its own first sample
    ws_d = 3 * 20 + 14 + 16 * 8                             # trapezoids over 20 s
    ws_b = 20 * 20
    assert repd.energy_wh == pytest.approx(ws_d / 3600)
    assert repb.energy_wh == pytest.approx(ws_b / 3600)
    assert c.delta["energy_wh"] == pytest.approx((ws_d - ws_b) / 3600)          # dispatched minus baseline
    assert c.delta["cost_usd"] == pytest.approx((ws_d - ws_b) / 3600 / 1e6 * 40)
    assert c.delta["co2_g"] == pytest.approx((ws_d - ws_b) / 3600 / 1000 * 250)
    rd, rb = Run.load(d), Run.load(b)
    assert share_under(rd, repd.window_start, repd.window_end, 10.0) == pytest.approx(17 / 21)
    assert share_under(rb, repb.window_start, repb.window_end, 10.0) == 0
    assert c.delta["under_cap_pct"] == pytest.approx(100 * 17 / 21)
    assert repd.baseline_w is None                          # no samples before the cap
    assert repd.time_to_compliance_s == 12                  # t3..t12 = 1*20 + 9*8 = 9.2 W: 10-s mean first <= 10 W at t12
    assert repb.time_to_compliance_s is None
    assert "time_to_compliance_s" not in c.delta and "chat_p95_s" not in c.delta   # no number on one side
    assert any("cap 10.00 W" in n for n in c.notes)


def test_cli_writes_table_and_chart(runs, tmp_path):
    root, _, _ = runs
    out = tmp_path / "reports"
    assert compare_cli.main(["--runs", str(root), "--out", str(out)]) == 0      # newest of each by default
    md = (out / "compare-run-d-vs-run-b-baseline.md").read_text(encoding="utf-8")
    assert "| Measured seconds at or under the cap | 81 % | 0 % | +81 points |" in md
    assert "time-to-first-token p95" in md
    assert (out / "compare-run-d-vs-run-b-baseline.png").stat().st_size > 0
