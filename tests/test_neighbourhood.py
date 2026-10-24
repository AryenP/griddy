"""The SIMULATED neighbourhood line (neighbourhood/model.py). Test doubles here are labelled: a fake executor
holding a load-forecast signal and measured-watts samples stands in for the runtime."""
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.timeline import Timeline
from core.types import GridSignal
from neighbourhood.model import Neighbourhood

CFG = {"line_limit_kw": 1000, "homes_offices_kw": [380, 720], "solar_kw": 260, "solar_day": [6.5, 18.5],
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
    now = (DAY + timedelta(hours=12)).timestamp()
    assert n.homes_kw(19.0, n.ex.signal, now) == pytest.approx(720.0)       # the forecast peak
    assert n.homes_kw(3.0, n.ex.signal, now) == pytest.approx(380.0)        # its lowest hour
    assert n.homes_kw(19.0, None, now) is None                              # no feed: no homes number
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
    assert ev.source == "simulated" and 10 <= ev.target_pct <= 95 and "simulated" in ev.reason
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


def test_a_multi_day_forecast_uses_today_only(tmp_path):
    # supervisor issue 13: ERCOT's forecast covers seven days; hours repeat, so only today's points may be used
    n = hood(tmp_path)
    tomorrow_flat = [(DAY + timedelta(days=1, hours=h), 30000.0) for h in range(24)]
    n.ex.signal = GridSignal(iso="TEST", location="fixture", price_now=50.0, load_forecast=FORECAST + tomorrow_flat)
    now = (DAY + timedelta(hours=12)).timestamp()
    assert n.homes_kw(19.0, n.ex.signal, now) == pytest.approx(720.0)
    assert n.homes_kw(3.0, n.ex.signal, now) == pytest.approx(380.0)


def test_the_cut_is_sized_for_the_worst_point_ahead(tmp_path):
    # Krish K1 #2: if our sites comply exactly with the call, the line never needs the diesel
    n = hood(tmp_path)
    t0 = 4_000_000.0
    n.start(now=t0)
    pct = None
    for s in range(91):
        w = 20.0 if pct is None else 20.0 * (1 - pct / 100)
        n.ex.power.append((t0 + s, w))
        n.tick(now=t0 + s)
        if n.pending_cap is not None:
            pct, n.pending_cap = n.pending_cap.target_pct, None
    assert pct is not None and n.last["diesel_kwh"] == 0.0 and n.last["diesel_off_kwh"] > 0


def test_idle_sites_do_not_drive_the_data_centers(tmp_path):
    # Krish K1 #3: an idle Mac's baseline is meter noise; the simulated data centers hold and the page says so
    from types import SimpleNamespace
    n = hood(tmp_path)
    n.ex.cal = SimpleNamespace(idle_w=0.5)
    n.cap_baseline_w = 1.2
    for t in range(10):
        n.ex.power.append((100.0 + t, 0.4))
    r, _ = n.response(110.0)
    assert r == 1.0 and n.nothing_to_shed


def test_stopping_the_replay_takes_back_its_call(tmp_path):
    # Krish K1 #6: the real cap the replay issued is withdrawn when it stops
    n = hood(tmp_path)
    t0 = 5_000_000.0
    n.start(now=t0)
    for s in range(91):
        n.ex.power.append((t0 + s, 20.0))
        n.tick(now=t0 + s)
        if n.cap_id:
            break
    call = n.cap_id
    assert call and n.pending_cap.source == "simulated"
    n.stop(now=t0 + 60)
    assert n.pending_withdraw == call


def test_no_cut_is_sent_when_our_sites_have_nothing_to_shed(tmp_path):
    # Krish K7: an idle Mac's baseline sits on its idle floor; a cut there only makes a shortfall and an operator ask
    from types import SimpleNamespace
    n = hood(tmp_path)
    n.ex.cal = SimpleNamespace(idle_w=0.5)
    n.ex.base = 1.2
    t0 = 6_000_000.0
    n.start(now=t0)
    for s in range(91):
        n.ex.power.append((t0 + s, 1.2))
        n.tick(now=t0 + s)
    assert n.pending_cap is None and n.cap_id is None and n.last["cut_skipped"] and n.last["nothing_to_shed"]
    assert n.last["diesel_kwh"] == pytest.approx(n.last["diesel_off_kwh"])   # nothing shed, same diesel


def _real_solar_profile():
    """A REAL CAISO day of solar (tests/fixtures/caiso_solar_20261023.csv, a saved pull; test data only)."""
    import pandas as pd

    from grid.watcher import solar_by_hour
    df = pd.read_csv(Path(__file__).parent / "fixtures" / "caiso_solar_20261023.csv", comment="#")
    return solar_by_hour([df], "US/Pacific")


def test_solar_follows_the_isos_measured_output_when_the_feed_has_it(tmp_path):
    profile, days = _real_solar_profile()
    assert days == "2026-10-23: 24 h" and max(profile) > 15000 and profile[2] == 0.0      # ~20 GW at noon, 0 at night
    n = hood(tmp_path)
    n.ex.signal = GridSignal(iso="CAISO", location="fixture", price_now=50.0, load_forecast=FORECAST,
                             solar_by_hour_mw=profile, solar_by_hour_days=days)
    peak_h = max(range(24), key=lambda h: profile[h])
    assert n.solar_kw(peak_h + 0.5, n.ex.signal) == pytest.approx(260.0)          # its peak hour at solar_kw
    assert n.solar_kw(2.5, n.ex.signal) == 0.0
    assert n.solar_kw(17.5, n.ex.signal) == pytest.approx(260.0 * profile[17] / max(profile))
    st = n.tick(now=time.time())
    assert st["solar_source"] == "shape of CAISO's measured solar output (2026-10-23: 24 h)" and "solar: shape of" in st["inputs"]
    n.ex.signal = GridSignal(iso="CAISO", location="fixture", price_now=50.0, load_forecast=FORECAST)
    assert "clear-day profile (no solar feed yet)" in n.tick(now=time.time())["inputs"]

