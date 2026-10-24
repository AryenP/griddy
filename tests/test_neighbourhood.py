"""The SIMULATED neighbourhood line (neighbourhood/model.py). Test doubles here are labelled: a fake executor
holding a load-forecast signal and measured-watts samples stands in for the runtime."""
from collections import deque
from datetime import datetime, timedelta

import pytest

from core.timeline import Timeline
from core.types import GridSignal
from neighbourhood.model import Neighbourhood

CFG = {"line_limit_kw": 1000, "homes_offices_peak_kw": 760, "solar_kw": 260, "solar_day": [6.5, 18.5],
       "data_centers": {"count": 20, "size_kw": [8, 30], "flexible_share": 0.6}, "diesel_kw": 600,
       "cap_trigger_pct": 95, "cap_margin_pct": 8, "scenario": {"name": "evening peak", "hours": [16, 21], "seconds": 90}}
DAY = datetime(2026, 10, 24).astimezone()
# a test-fixture forecast: 20 GW at night rising to a 40 GW peak at 19:00
FORECAST = [(DAY + timedelta(hours=h), 20000 + 20000 * max(0.0, 1 - abs(h - 19) / 8)) for h in range(24)]


class FakeExecutor:
    def __init__(self):
        self.signal = GridSignal(iso="TEST", location="fixture", price_now=50.0, load_forecast=FORECAST)
        self.power: deque = deque(maxlen=3600)
        self.base = 20.0

    def baseline_w(self):
        return self.base


def hood(tmp_path, cfg=CFG):
    return Neighbourhood(Timeline(run_id="n", root=tmp_path), FakeExecutor(), cfg=cfg)


def test_nothing_configured_changes_nothing(tmp_path):
    n = hood(tmp_path, cfg={})
    assert not n.enabled and n.tick(now=0.0) is None


def test_homes_follow_the_forecast_shape(tmp_path):
    n = hood(tmp_path)
    assert n.homes_kw(19.0, n.ex.signal) == pytest.approx(760.0)            # the forecast peak
    assert n.homes_kw(3.0, n.ex.signal) == pytest.approx(760 * 20000 / 40000)
    assert n.homes_kw(19.0, None) is None                                   # no feed: no homes number
    assert n.solar_kw(12.5) == pytest.approx(260.0) and n.solar_kw(20.0) == 0.0


def test_data_centers_follow_our_measured_response(tmp_path):
    n = hood(tmp_path)
    full = n.dc_kw(1.0)
    assert full == pytest.approx(sum(n.dc_sizes)) and len(n.dc_sizes) == 20 and n.dc_sizes[0] == 8 and n.dc_sizes[-1] == 30
    assert n.dc_kw(0.1) == pytest.approx(full * (0.4 + 0.6 * 0.1))
    n.cap_baseline_w = 20.0
    for t in range(10):
        n.ex.power.append((100.0 + t, 2.0))                                # our sites now draw 10 % of baseline
    r, mean = n.response(110.0)
    assert r == pytest.approx(0.1) and mean == pytest.approx(2.0)


def test_the_evening_peak_calls_for_a_cut_and_counts_diesel(tmp_path):
    n = hood(tmp_path)
    t0 = 1_000_000.0
    n.start(now=t0)
    caps, states = [], []
    for s in range(91):
        n.ex.power.append((t0 + s, 20.0))                                  # our sites ignore the cut (Brownout off)
        st = n.tick(now=t0 + s)
        states.append(st)
        if n.pending_cap is not None:
            caps.append(n.pending_cap)
            n.pending_cap = None
    assert len(caps) == 1                                                  # one call per replay
    ev = caps[0]
    assert ev.source == "ui" and 10 <= ev.target_pct <= 95 and "simulated" in ev.reason
    peak = max(states, key=lambda x: x["demand_kw"])
    assert peak["simulated"] is True and peak["loading_pct"] > 100 and peak["diesel_kw"] > 0
    assert states[-1]["diesel_kwh"] == pytest.approx(states[-1]["diesel_off_kwh"])   # nobody shed: same diesel
    assert all(x["line_kw"] <= 1000 + 1e-6 for x in states)               # diesel covers what the line cannot


def test_shedding_avoids_diesel(tmp_path):
    n = hood(tmp_path)
    t0 = 2_000_000.0
    n.start(now=t0)
    for s in range(91):
        w = 20.0 if n.cap_id is None else 1.0                              # our sites shed once the cut is called
        n.ex.power.append((t0 + s, w))
        n.tick(now=t0 + s)
        n.pending_cap = None
    last = n.last
    assert last["diesel_kwh"] < last["diesel_off_kwh"]                     # diesel avoided, in simulated kWh


def test_no_cut_without_a_baseline_for_our_sites(tmp_path):
    n = hood(tmp_path)
    n.ex.base = None
    t0 = 3_000_000.0
    n.start(now=t0)
    for s in range(91):
        n.tick(now=t0 + s)
    assert n.pending_cap is None and n.cap_id is None
