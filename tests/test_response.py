"""Griddy's automatic emergency response (response/engine.py) on the REAL Texas Medical Center map
(docs/evidence/city/houston-map.json, OpenStreetMap). The executor, replay and what-if here are labelled test doubles;
the feeders, switching and crews are simulated in the product too, and every step says so."""
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from agent.channels.crews import bid_for, pick
from response.engine import Response, kind_for

ROOT = Path(__file__).resolve().parents[1]


class TL:                       # TEST DOUBLE timeline: keeps what was logged
    def __init__(self):
        self.lines = []

    def log(self, kind, **d):
        self.lines.append((kind, d))


def rig(watts=20.0, t0=1000.0):
    ex = NS(power=[(t0 - 30 + i, watts) for i in range(30)], signal=None)          # TEST DOUBLE executor
    rp = NS(event=None, baseline_w=None, pending_caps=[], pending_withdraw=[], caps={}, last=None)   # TEST DOUBLE replay
    wi = NS(last=None, active=lambda now: False, cap_id=None)                      # TEST DOUBLE what-if
    return Response(TL(), ex, rp, wi, ROOT), ex, rp


def test_the_judges_words_pick_the_incident():
    assert kind_for("hub") == "substation"
    assert kind_for("hub", "a tree fell on the power line") == "line"
    assert kind_for("city", "everyone plugs in their EV at 6 pm") == "ev_surge"
    assert kind_for("plant:Solar", "rooftop solar backfeed") == "solar_backfeed"
    assert kind_for("city") == "demand_surge" and kind_for("plant:Gas") == "plant"
    with pytest.raises(KeyError):
        kind_for("the moon")


def test_a_substation_fire_is_isolated_hospitals_islanded_rerouted_shed_and_a_crew_sent_in_order():
    r, ex, rp = rig()
    r.start("substation", now=1000.0)
    for s in range(1, 7):
        st = r.tick(1000.0 + s)
    assert [x["step"] for x in st["steps"]] == ["detect", "isolate", "protect", "reroute", "shed", "dispatch"]
    assert st["steps"][0]["kind"] == "what-if" and all(x["kind"] != "real" for x in st["steps"])
    assert st["hospitals"] == "central plants" and st["lit_with"] > st["lit_without"] == 0.0
    assert len(rp.pending_caps) == 1 and rp.pending_caps[0].target_pct == 40      # the one real actuation, asked once
    o = r.open_orders()[0]
    assert set(o["routes"]) == {"crew-1", "crew-2", "crew-3"} and all(v["m"] > 0 for v in o["routes"].values())


def test_the_crew_repairs_and_everything_is_given_back():
    r, ex, rp = rig()
    r.start("substation", now=1000.0)
    for s in range(1, 6):
        r.tick(1000.0 + s)
    o = r.open_orders()[0]
    r.crew_update(o["id"], "crew-3", "assigned", 130, [{"crew": "crew-3", "can": True, "eta_s": 130}], now=1010.0)
    assert r.open_orders() == []
    with pytest.raises(KeyError):
        r.crew_update(o["id"], "crew-9", "en_route", now=1011.0)
    st = r.crew_update(o["id"], "crew-3", "repaired", now=1020.0)
    assert st["done"] and st["lit_with"] == 1.0 and st["steps"][-1]["step"] == "restore"
    assert rp.pending_withdraw                                                     # the cap goes back
    assert r.tick(1020.0 + 9) is None and r.last is None                          # and the incident closes


def test_an_ev_surge_sheds_before_it_switches_and_needs_no_crew():
    r, ex, rp = rig()
    r.start("ev_surge", now=1000.0)
    st = None
    for s in range(1, 6):
        st = r.tick(1000.0 + s)
    assert st["steps"][1]["step"] == "shed" and st["order"] is None and st["lit_with"] == 1.0 > st["lit_without"]


def test_crews_bid_with_their_skills_and_the_soonest_able_crew_wins():
    order = {"id": "wo-1", "kind": "line", "speed_mps": 10.0,
             "routes": {"crew-1": {"m": 500}, "crew-2": {"m": 2000}, "crew-3": {"m": 1000}}}
    crews = [{"id": "crew-1", "skills": ["substation"]}, {"id": "crew-2", "skills": ["line"]}, {"id": "crew-3", "skills": ["substation", "line"]}]
    bids = [bid_for(c, order, busy=False) for c in crews]
    assert [b["can"] for b in bids] == [False, True, True] and pick(bids)["crew"] == "crew-3"
    assert pick([bid_for(crews[2], order, busy=True)]) is None
