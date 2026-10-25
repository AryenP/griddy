"""What-if faults (replay/whatif.py): the fault is invented, its size comes from the real grid at that moment. The
replayed event data is REAL (EIA-930 files in docs/evidence/events/); the executor and the live signal here are labelled
test doubles."""
import time
from collections import deque
from datetime import datetime, timedelta

import pytest

from core.timeline import Timeline
from replay.engine import Replay
from replay.whatif import WhatIf


class FakeExecutor:            # TEST DOUBLE: the runtime's measured watts, calibration and last grid signal
    def __init__(self, signal=None):
        self.power: deque = deque(maxlen=3600)
        self.cal = type("Cal", (), {"idle_w": 1.5})()
        self.signal = signal


def rig(tmp_path, watts=20.0, signal=None):
    t0 = time.time()
    ex = FakeExecutor(signal)
    for k in range(300):
        ex.power.append((t0 - 60 + k, watts))         # measured before and through the fault
    tl = Timeline(run_id="w", root=tmp_path)
    r = Replay(tl, ex)
    return WhatIf(tl, ex, r, {"seconds": 60, "emergency_cut_pct": 40}), r, ex, t0


def test_tripping_a_plant_removes_its_real_output_and_asks_our_sites_for_a_cut(tmp_path):
    w, r, ex, t0 = rig(tmp_path)
    r.start("uri-2021", now=t0)
    real = r.tick(now=t0 + 60)                              # mid-event: ERCOT's real hour from EIA-930
    r.pending_caps.clear()                                  # the replay's own alerts are not under test here
    st = w.start("plant:Gas", now=t0 + 60)
    assert st["lost_mw"] == pytest.approx(real["mix_mw"]["Natural Gas"]) and st["fuel"] == "Gas"
    assert st["served_after"] == pytest.approx(real["demand_mw"] - real["mix_mw"]["Natural Gas"])
    assert st["shortfall_mw"] > 0 and st["asked_cut_pct"] == 40 and "EIA-930" in st["source"]
    cap = r.pending_caps.pop()
    assert cap.source == "whatif" and cap.target_w == pytest.approx(12.0) and "short" in cap.reason
    for k in range(10):
        ex.power.append((t0 + 61 + k, 12.0))                # the Mac's measured response
    ex.power = deque(sorted(ex.power), maxlen=3600)
    ex.power = deque([(t, w) for t, w in ex.power if not (t0 + 61 <= t < t0 + 71) or w == 12.0], maxlen=3600)
    st = w.tick(now=t0 + 71)
    assert st["measured_cut_pct"] > 0 and st["scale"]["share_pct"] <= 40 and st["scale"]["people"] > 0


def test_the_hub_cuts_off_the_largest_fleet_and_the_city_surges_to_the_days_real_peak(tmp_path):
    w, r, _, t0 = rig(tmp_path)
    r.start("caiso-2022-09", now=t0)
    real = r.tick(now=t0 + 5)
    big = max(("Gas", "Solar", "Nuclear", "Wind", "Hydro"), key=lambda n: w.fleet_mw(real["mix_mw"], n))
    assert w.start("hub", now=t0 + 5)["fuel"] == big
    st = w.start("city", now=t0 + 6)                        # a second fault replaces the first and withdraws its cap
    assert st["needed_after"] == pytest.approx(51144.0)     # the rest of 6 Sep's published forecast peaks at 18:00
    assert st["surge_mw"] > 0 and st["lost_mw"] == 0


def test_a_fault_ends_by_itself_or_on_clear_and_withdraws_its_cut(tmp_path):
    w, r, _, t0 = rig(tmp_path)
    r.start("uri-2021", now=t0)
    r.tick(now=t0 + 60)
    r.pending_caps.clear()
    w.start("plant:Gas", now=t0 + 60)
    cap = r.pending_caps.pop()
    assert w.tick(now=t0 + 60 + w.seconds + 1) is None and cap.id in r.pending_withdraw and w.fault is None
    w.start("plant:Gas", now=t0 + 70)
    cap = r.pending_caps.pop()
    w.end()
    assert cap.id in r.pending_withdraw and w.fault is None


def test_live_grid_uses_the_isos_fuel_mix_and_forecast(tmp_path):
    now = datetime.now().astimezone()
    sig = type("Sig", (), {"iso": "CAISO",                # TEST DOUBLE: shaped like core.types.GridSignal
                           "fuel_mix_mw": {"Natural Gas": 9000.0, "Biogas": 200.0, "Solar": 12000.0, "Imports": 4000.0},
                           "load_forecast": [(now, 25000.0), (now + timedelta(hours=3), 31000.0)]})()
    w, _, _, _ = rig(tmp_path, signal=sig)
    st = w.start("plant:Gas")
    assert st["lost_mw"] == 9000.0                          # natural gas only: biogas is not the gas fleet
    assert st["served_before"] == 25200.0 and st["needed_before"] == 25000.0 and "live" in st["source"]
    assert w.start("city")["needed_after"] == 31000.0


def test_nothing_to_break_or_nothing_running_says_so(tmp_path):
    w, r, ex, t0 = rig(tmp_path, watts=2.0)                 # idle Mac: nothing to shed
    r.start("caiso-2020-08", now=t0)
    r.tick(now=t0 + 5)
    r.pending_caps.clear()
    with pytest.raises(KeyError):
        w.start("plant:Unobtainium")
    st = w.start("plant:Gas", now=t0 + 5)
    assert st["nothing_to_shed"] and not r.pending_caps


def test_the_route_breaks_only_named_parts_from_a_joined_device(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api import access
    from api.routes import make_router
    monkeypatch.setattr(access.settings, "operator_token", "t")
    w, _, _, _ = rig(tmp_path)                              # no grid signal yet: nothing to size a fault from
    rt = type("RT", (), {"tl": w.tl, "whatif": w})()      # TEST DOUBLE runtime: the two attributes the route uses
    app = FastAPI()
    app.include_router(make_router(rt))
    stranger, joined = TestClient(app), TestClient(app, headers={access.HEADER: "t"})
    assert stranger.post("/api/whatif", json={"target": "hub"}).status_code == 401
    assert joined.post("/api/whatif", json={"target": "plant:Gas; rm -rf"}).status_code == 422
    assert joined.post("/api/whatif", json={"target": "plant:Unobtainium"}).status_code == 404
    r = joined.post("/api/whatif", json={"target": "plant:Gas"})
    assert r.status_code == 409 and "no grid numbers" in r.json()["detail"]
    assert joined.post("/api/whatif", json={"target": "clear"}).json() == {"cleared": True}
