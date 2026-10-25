"""What-if: a judge breaks a part of the grid, and the live software reacts (Aryen, Sat evening: "where judges can break
the project wherever they select and it still reacts").

The fault is invented, and the page says "what-if". Its SIZE is real: tripping a plant removes that fuel's real output
at this moment (the replayed event's EIA-930 hour, or the ISO's live fuel mix); a demand surge raises demand to the real
day-ahead forecast peak for the rest of the same day (published the day before: nothing from later). The grid's shortfall is arithmetic on those real numbers, and the response is
real: when the grid is short, the cut goes to the real dispatcher as a cap on our sites, below their measured baseline,
and this Mac's measured watts are what they are. At scale: the cut the grid asked, as far as our sites delivered it,
applied to the grid's flexible load, against the shortfall.
"""
from __future__ import annotations

import re
import time
from datetime import datetime

import pandas as pd

from core.timeline import Timeline
from core.types import CapEvent

FUELS = [("Gas", r"natural gas|^gas$"), ("Coal", r"coal"), ("Nuclear", r"nuclear"), ("Wind", r"wind"), ("Solar", r"solar"),
         ("Hydro", r"hydro"), ("Imports", r"import")]


def _now_value(points, now: float) -> float | None:
    """The load forecast point nearest now, within two hours."""
    best = None
    for t, mw in points or []:
        ts = t.timestamp() if hasattr(t, "timestamp") else datetime.fromisoformat(str(t)).timestamp()
        d = abs(ts - now)
        if best is None or d < best[0]:
            best = (d, float(mw))
    return best[1] if best and best[0] < 7200 else None


def _live_day_peak(points, now: float) -> tuple[float | None, str | None]:
    """The highest point of the ISO's load forecast for the current local day (published the day before)."""
    pts = [(t if hasattr(t, "timestamp") else datetime.fromisoformat(str(t)), float(mw)) for t, mw in points or []]
    if not pts:
        return None, None
    today = datetime.fromtimestamp(now, pts[0][0].tzinfo).date()
    day = [(t, mw) for t, mw in pts if t.date() == today]
    if not day:
        return None, None
    t, mw = max(day, key=lambda x: x[1])
    return mw, t.isoformat()


class WhatIf:
    def __init__(self, tl: Timeline, executor, replay, cfg: dict | None = None):
        self.tl, self.ex, self.replay = tl, executor, replay
        self.cfg = cfg or {}
        self.seconds = float(self.cfg.get("seconds", 60))
        self.min_surge = float(self.cfg.get("min_surge_mw", 500))   # a smaller surge reads as "+0.0 GW": refuse it
        self.fault: dict | None = None
        self.cap_id: str | None = None
        self.last: dict | None = None

    def active(self, now: float) -> bool:
        return self.fault is not None and now - self.fault["t0"] < self.seconds

    # ------------------------------------------------------------------ the grid as it is right now
    def grid_now(self, now: float) -> dict:
        r = self.replay
        if r.event is not None and r.last:
            ev = r.event
            return {"source": f"{ev['title']}, {ev['when']} (EIA-930, {ev['ba']})", "mix": dict(r.last.get("mix_mw") or {}),
                    "served": r.last.get("demand_mw"), "needed": r.last.get("forecast_mw"),
                    "peak_needed": (pk := self._day_peak(now))[0], "peak_at": pk[1], "flexible_mw": ev.get("flexible_mw"),
                    "flexible_source": ev.get("flexible_source"), "event": ev["id"],
                    "people_per_mw": ev["people_out"] / ev["shed_mw"] if ev.get("people_out") and ev.get("shed_mw") else None,
                    "people_unit": ev.get("people_unit", "people")}
        sig = self.ex.signal
        mix = dict(sig.fuel_mix_mw) if sig else {}
        served = sum(v for v in mix.values() if v > 0) or None
        needed = _now_value(sig.load_forecast if sig else [], now)
        peak, peak_at = _live_day_peak(sig.load_forecast if sig else [], now)
        return {"source": f"{sig.iso} live (gridstatus)" if sig else "no grid feed", "mix": mix, "served": served,
                "needed": needed or served, "peak_needed": peak, "peak_at": peak_at,
                "flexible_mw": 1000.0, "flexible_source": "per 1 GW of data centers (illustrative unit)", "event": None,
                "people_per_mw": None, "people_unit": None}

    def _day_peak(self, now: float) -> tuple[float | None, str | None]:
        """The highest day-ahead forecast of the replayed day: published the day before, so known then."""
        r = self.replay
        t = pd.Timestamp(r.sim_time(now))
        fc = r.data(r.event["id"])["demand_forecast_mw"].dropna()
        day = pd.Series((fc.index - pd.Timedelta(hours=1)).date, index=fc.index)
        today = fc[day == t.date()]
        return (float(today.max()), today.idxmax().isoformat()) if len(today) else (None, None)

    # ------------------------------------------------------------------ break something
    def fleet_mw(self, mix: dict, name: str) -> float:
        pat = dict(FUELS)[name]
        return sum(v for k, v in mix.items() if re.search(pat, k, re.I) and v > 0)

    def parts(self, now: float | None = None) -> dict[str, float | None]:
        """What can break right now and its real size: each producing fleet's MW, the substation (the largest fleet),
        the city (the surge to the day's published forecast peak, if any)."""
        now = time.time() if now is None else now
        g = self.grid_now(now)
        out = {f"plant:{n}": mw for n, _ in FUELS if (mw := self.fleet_mw(g["mix"], n)) > 0}
        if out:
            out["hub"] = max(out.values())
        if g["peak_needed"] and g["needed"] and g["peak_needed"] - g["needed"] >= self.min_surge:
            out["city"] = g["peak_needed"] - g["needed"]
        return out

    def start(self, target: str, now: float | None = None, share_pct: float = 100.0, cause: str = "") -> dict:
        """Break `target`: `share_pct` of its real size at this moment (all of it by default). `cause` is the judge's
        own words (agent/faults.py), shown in the label."""
        now = time.time() if now is None else now
        share = max(1.0, min(100.0, float(share_pct))) / 100
        if target not in ("hub", "city") and not (target.startswith("plant:") and target[6:] in dict(FUELS)):
            raise KeyError(target)
        g = self.grid_now(now)
        if g["served"] is None or g["needed"] is None:
            raise ValueError("no grid numbers yet: the fault needs the grid's real supply and demand")
        lost, surge, label, fuel = 0.0, 0.0, "", None
        if target.startswith("plant:"):
            fuel = name = target.split(":", 1)[1]
            if name not in dict(FUELS):
                raise KeyError(target)
            whole = self.fleet_mw(g["mix"], name)
            if whole <= 0:
                raise ValueError(f"{name} produces nothing right now: nothing to trip")
            lost = whole * share
            label = (f"What-if: the {name.lower()} fleet trips, -{lost / 1000:.1f} GW (its real output at this moment)" if share == 1
                     else f"What-if: the {name.lower()} fleet loses {share:.0%}, -{lost / 1000:.1f} GW of its real {whole / 1000:.1f} GW now")
        elif target == "hub":
            fuel, whole = max(((n, self.fleet_mw(g["mix"], n)) for n, _ in FUELS), key=lambda x: x[1])
            lost = whole * share
            label = (f"What-if: the main substation fails and cuts off the {fuel.lower()} fleet, -{lost / 1000:.1f} GW (its real output)"
                     if share == 1 else f"What-if: the main substation fails and cuts off {share:.0%} of the {fuel.lower()} fleet, -{lost / 1000:.1f} GW")
        elif target == "city":
            gap = (g["peak_needed"] or 0) - (g["needed"] or 0)
            if gap < self.min_surge:
                raise ValueError(f"demand is within {max(gap, 0) / 1000:.1f} GW of today's forecast peak: nothing to surge; trip a plant instead")
            surge = gap * share
            at = f" ({g['peak_at'][11:16]})" if g.get("peak_at") else ""
            label = (f"What-if: demand jumps to today's forecast peak{at}, +{surge / 1000:.1f} GW (the operator's real forecast)" if share == 1
                     else f"What-if: demand jumps {share:.0%} of the way to today's forecast peak{at}, +{surge / 1000:.1f} GW")
        else:
            raise KeyError(target)
        if cause:
            label = f"{label}. Cause, in the judge's words: {cause}"
        served_after = g["served"] - lost
        needed_after = g["needed"] + surge
        shortfall = max(0.0, needed_after - served_after)
        xs = [w for t, w in self.ex.power if now - 20 <= t <= now]
        baseline = sum(xs) / len(xs) if xs else None
        if self.replay.event is not None and self.replay.baseline_w:   # during a replay: the baseline from before it
            baseline = self.replay.baseline_w
        idle = getattr(getattr(self.ex, "cal", None), "idle_w", 0.0) or 0.0
        nothing = baseline is not None and baseline - idle < float(self.cfg.get("min_flexible_w", 3.0))
        asked = float(self.cfg.get("emergency_cut_pct", 40)) if shortfall > 0 else 0.0
        self.end(now)
        self.fault = {"t0": now, "target": target, "fuel": fuel, "label": label, "share_pct": 100 * share, "cause": cause, "lost_mw": lost, "surge_mw": surge,
                      "grid": g, "served_after": served_after, "needed_after": needed_after, "shortfall_mw": shortfall,
                      "baseline_w": baseline, "asked_cut_pct": asked, "nothing_to_shed": nothing}
        if asked and baseline and not nothing:
            ev = CapEvent(source="whatif", start=datetime.fromtimestamp(now).astimezone(), duration_s=int(self.seconds) + 5,
                          target_w=baseline * (1 - asked / 100), target_pct=asked,
                          reason=f"{label}: the grid is {shortfall / 1000:.1f} GW short", raw=g["source"])
            self.cap_id = ev.id
            self.replay.pending_caps.append(ev)
        self.tl.log("note", msg=label, whatif=target, lost_mw=lost, surge_mw=surge, shortfall_mw=shortfall,
                    asked_cut_pct=asked, source=g["source"])
        return self.tick(now)

    def end(self, now: float | None = None) -> None:
        if self.cap_id:
            self.replay.pending_withdraw.append(self.cap_id)
        if self.fault is not None:
            self.tl.log("note", msg="what-if over: the fault is cleared", whatif=self.fault["target"])
        self.fault, self.cap_id = None, None

    def tick(self, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        if self.fault is None:
            return None
        if not self.active(now):
            self.end(now)
            self.last = None
            return None
        f, g = self.fault, self.fault["grid"]
        xs = [w for t, w in self.ex.power if t > now - 10]
        ours = sum(xs) / len(xs) if xs else None
        cut = (1 - ours / f["baseline_w"]) if ours is not None and f["baseline_w"] and self.cap_id else None
        scale = None
        if cut is not None and cut > 0 and f["shortfall_mw"] > 0:
            share = min(1.0, cut, f["asked_cut_pct"] / 100)
            freed = float(g["flexible_mw"]) * share
            scale = {"freed_mw": freed, "share_pct": 100 * share, "flexible_mw": g["flexible_mw"],
                     "flexible_source": g["flexible_source"], "share_of_shortfall_pct": 100 * freed / f["shortfall_mw"],
                     "people": round(g["people_per_mw"] * freed) if g["people_per_mw"] else None, "people_unit": g["people_unit"]}
        state = {"t": now, "whatif": True, "target": f["target"], "fuel": f["fuel"], "label": f["label"],
                 "share_pct": f["share_pct"], "cause": f["cause"],
                 "source": g["source"], "event": g["event"], "mix_mw": g["mix"], "nothing_to_shed": f["nothing_to_shed"],
                 "lost_mw": f["lost_mw"], "surge_mw": f["surge_mw"], "served_before": g["served"], "needed_before": g["needed"],
                 "served_after": f["served_after"], "needed_after": f["needed_after"], "shortfall_mw": f["shortfall_mw"],
                 "asked_cut_pct": f["asked_cut_pct"], "baseline_w": f["baseline_w"], "ours_w": ours,
                 "measured_cut_pct": None if cut is None else 100 * cut, "remaining_s": self.seconds - (now - f["t0"]),
                 "scale": scale}
        self.last = state
        self.tl.log("whatif", **state)
        return state
