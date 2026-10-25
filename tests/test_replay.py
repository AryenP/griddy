"""Replays of real grid emergencies (replay/engine.py, config/events.yaml). The event data is REAL (EIA-930 files in
docs/evidence/events/); the executor here is a labelled test double holding measured-watts samples."""
import time
from collections import deque

import pytest

from core import config
from core.timeline import Timeline
from replay.engine import Replay


class FakeExecutor:            # TEST DOUBLE: the runtime's measured watts and calibration
    def __init__(self):
        self.power: deque = deque(maxlen=3600)
        self.cal = type("Cal", (), {"idle_w": 1.5})()


def rig(tmp_path, watts=20.0, t0=None):
    t0 = time.time() if t0 is None else t0
    ex = FakeExecutor()
    for k in range(60):
        ex.power.append((t0 - 60 + k, watts))     # the baseline is the last 20 s of these
    return Replay(Timeline(run_id="r", root=tmp_path), ex), ex, t0


def test_catalog_is_three_real_events_with_cited_alerts_and_their_hours(tmp_path):
    r, _, _ = rig(tmp_path)
    cat = {e["id"]: e for e in r.catalog()}
    assert set(cat) == {"uri-2021", "caiso-2020-08", "caiso-2022-09"}
    for e in cat.values():
        assert e["series"] and all(len(p) == 3 for p in e["series"]) and "EIA-930" in e["data_source"]
        assert e["alerts"] and all(a["source"] for a in e["alerts"]) and e["impact"]
        assert all(i["source"] for i in e["impact"])
    uri = cat["uri-2021"]
    assert max(p[2] for p in uri["series"]) > 70000                     # ERCOT forecast above 70 GW
    assert min(p[1] for p in uri["series"]) < 46000                      # served demand fell to ~44 GW: load shed
    flags = {e: [a for a in cat[e]["alerts"] if a["kind"] == "brownout"] for e in cat}
    assert flags["uri-2021"] and flags["caiso-2022-09"] and not flags["caiso-2020-08"]   # forecast above the prior record
    assert "65,750 MW record" in flags["uri-2021"][0]["label"]


def test_alerts_reach_the_dispatcher_at_their_real_times_and_end(tmp_path):
    r, ex, t0 = rig(tmp_path)
    r.start("caiso-2022-09", now=t0)
    assert r.baseline_w == pytest.approx(20.0) and not r.nothing_to_shed
    st = r.tick(now=t0 + 0.5)                       # the Flex Alert days before and Brownout's flag fire at once
    assert st["demand_mw"] and st["forecast_mw"] and st["carbon_g_kwh"] > 0
    assert st["mix_mw"]["Natural Gas"] > 10000 and {"Solar", "Wind", "Nuclear"} <= set(st["mix_mw"])   # EIA-930, real
    warn = r.pending_caps.pop()                     # Brownout's own flag asks the warning cut, replacing the Flex Alert's
    flex = r.pending_caps.pop()
    assert "Flex Alert" in flex.reason and r.pending_withdraw == [flex.id]
    assert warn.source == "replay" and warn.target_w == pytest.approx(16.0) and "Brownout's flag" in warn.reason
    r.pending_withdraw.clear()
    eea3 = next(a for a in r.catalog()[2]["alerts"] if "EEA 3" in a["label"] and a["kind"] == "emergency")
    r.tick(now=t0 + eea3["replay_s"] + 0.1)
    deep = r.pending_caps.pop()
    assert deep.target_w == pytest.approx(12.0) and r.caps.keys() == {"warning", "emergency"}
    end = next(a for a in r.catalog()[2]["alerts"] if a["kind"] == "end")
    r.tick(now=t0 + end["replay_s"] + 0.1)
    assert r.pending_withdraw == [deep.id] and r.caps.keys() == {"warning"}
    r.tick(now=t0 + r.seconds + 1)                  # the replay ends: everything withdrawn
    assert warn.id in r.pending_withdraw and r.event is None


def test_measured_cut_scales_to_the_events_own_numbers(tmp_path):
    r, ex, t0 = rig(tmp_path)
    r.start("uri-2021", now=t0)
    r.tick(now=t0 + 0.5)
    for k in range(10):                              # our sites drop to 12 W: a measured 40 % cut
        ex.power.append((t0 + 1 + k, 12.0))
    st = r.tick(now=t0 + 11)
    assert st["measured_cut_pct"] == pytest.approx(40.0) and st["asked_cut_pct"] == 20.0
    sc = st["scale"]                                 # credited: the 20 % asked, not the 40 % this Mac happened to shed
    assert sc["share_pct"] == pytest.approx(20.0) and sc["freed_mw"] == pytest.approx(4132 * 0.2)
    assert sc["share_of_shed_pct"] == pytest.approx(100 * 4132 * 0.2 / 20000)
    assert sc["people"] == round(4_500_000 / 20000 * 4132 * 0.2)


def test_nothing_to_shed_sends_no_cut(tmp_path):
    r, _, t0 = rig(tmp_path, watts=2.0)              # an idle Mac: 2 W against a 1.5 W idle floor
    r.start("caiso-2020-08", now=t0)
    r.tick(now=t0 + 0.5)
    assert r.nothing_to_shed and not r.pending_caps


def test_grid_scale_estimate_is_arithmetic_on_cited_numbers():
    """grid/scale.py: an ESTIMATE, labelled so; every input is in config/site.yaml with its source."""
    from grid.scale import estimate
    cfg = config.site["scale"]
    x = estimate(cfg, 62168.0, "2026-10-24T16:50:30-05:00")
    assert x["estimate"] is True and x["iso"] == "ERCOT"
    assert x["freed_mw"] == pytest.approx(cfg["large_loads_running_mw"] * cfg["our_cut_pct"] / 100)
    assert x["share_of_demand_pct"] == pytest.approx(100 * x["freed_mw"] / 62168.0)
    assert all(cfg[k].startswith("https://") for k in ("large_loads_url", "queue_url"))
    assert estimate(cfg, None, None)["share_of_demand_pct"] is None


@pytest.mark.parametrize("eid", ["uri-2021", "caiso-2020-08", "caiso-2022-09"])
def test_the_replay_never_sees_the_future(tmp_path, eid):
    """Delete every hour after the replayed moment (keeping only the day-ahead forecasts for the rest of that day,
    which the operator had published the day before): the software sees and does exactly the same."""
    import pandas as pd
    for s_into in (0.5, 30.0, 61.0, 95.0, 119.0):
        full, ex, t0 = rig(tmp_path)
        blind = Replay(Timeline(run_id="b", root=tmp_path), ex)
        full.start(eid, now=t0)
        blind.start(eid, now=t0)
        t = full.sim_time(t0 + s_into)
        s = full.data(eid).copy()
        later = s.index > pd.Timestamp(t)
        s.loc[later, [c for c in s.columns if c != "demand_forecast_mw"]] = float("nan")
        later_days = pd.Series((s.index - pd.Timedelta(hours=1)).date, index=s.index) > t.date()
        s.loc[later_days, "demand_forecast_mw"] = float("nan")
        blind.series[eid] = s
        a, b = full.tick(now=t0 + s_into), blind.tick(now=t0 + s_into)
        for k in ("demand_mw", "forecast_mw", "mix_mw", "hour_ending", "fired", "cut_kinds", "asked_cut_pct"):
            assert a[k] == b[k], (eid, s_into, k)
        assert [c.target_w for c in full.pending_caps] == [c.target_w for c in blind.pending_caps]


def test_live_fetch_is_used_and_an_unreachable_api_falls_back_to_the_evidence_copy(tmp_path, monkeypatch):
    import pandas as pd
    from replay import eia
    r, _, _ = rig(tmp_path)
    ev = r.events["uri-2021"]
    evidence = pd.read_csv(ev["data"], comment="#")
    monkeypatch.setattr(eia, "fetch", lambda e, timeout=8.0: (evidence.copy(), {"source": "live", "rows": len(evidence)}))
    meta = r.prepare("uri-2021")                     # TEST DOUBLE for the network: the API's answer is the same hours
    assert meta["source"] == "live" and meta["max_diff_mw"] == 0.0
    def down(e, timeout=8.0):
        raise OSError("network unreachable")
    monkeypatch.setattr(eia, "fetch", down)
    r.cache.got.clear()
    meta = r.prepare("uri-2021")
    assert meta["source"] == "evidence copy" and "unreachable" in meta["why"] and len(r.data("uri-2021")) == len(evidence)


def test_the_live_api_rows_become_the_evidence_columns(monkeypatch):
    from replay import eia
    rows = {"region-data": [{"period": "2021-02-15T03", "type": "D", "value": "68862"},     # shaped like api.eia.gov v2
                            {"period": "2021-02-15T03", "type": "DF", "value": "70522"}],
            "fuel-type-data": [{"period": "2021-02-15T03", "fueltype": "NG", "value": "43967"},
                               {"period": "2021-02-15T03", "fueltype": "WND", "value": "7642"}]}
    monkeypatch.setattr(eia, "_get", lambda path, params, timeout: rows[path])
    df, meta = eia.fetch({"window": ["2021-02-14T18:00", "2021-02-15T21:00"], "ba": "ERCO"})
    assert list(df["utc_end"]) == ["2021-02-15T03:00:00Z"] and df.loc[0, "demand_mw"] == 68862.0
    assert df.loc[0, "Natural Gas"] == 43967.0 and df.loc[0, "Wind"] == 7642.0 and meta["source"] == "live"
