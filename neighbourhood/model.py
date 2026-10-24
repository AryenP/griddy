"""A SIMULATED neighbourhood power line around Brownout's real, measured sites (config/neighbourhood.yaml).

Simulated, and labelled so on screen (Aryen's decision, Sat 05:35): the homes and offices, the solar farm,
twenty data centers, the line's limit and a diesel generator. Driven by real inputs where one exists:
  - homes and offices: the shape of today's real ISO load forecast (GridSignal.load_forecast), scaled so the
    day's lowest hour at `homes_offices_kw[0]` and its peak at `homes_offices_kw[1]`;
  - solar: a clear-day profile between `solar_day` hours (simulated outright);
  - data centers: each has a fixed size; its flexible share follows OUR sites' measured response, i.e. our
    fleet's measured watts as a fraction of its 60-s baseline before the cap. Brownout on: our machines shed
    and the simulated ones follow. Brownout off: our machines keep running and so do they.
When the line reaches `cap_trigger_pct` of its limit, the utility's call goes to the REAL dispatcher as a CapEvent
(a % cut sized to bring the line back under its limit), so the real machines respond for real. Whatever the
line still cannot carry, the diesel generator covers. The counterfactual "Brownout off" diesel (our sites at
their baseline) is computed every second for the "diesel avoided" figure.

`start()` replays a stretch of today's forecast (`scenario.hours`) in `scenario.seconds` real seconds; the
energy figures integrate over that replayed (simulated) time. Our sites' watts are added as measured.
"""
from __future__ import annotations

import math
import time
from bisect import bisect_right
from collections import deque
from datetime import datetime

from core import config
from core.timeline import Timeline
from core.types import CapEvent, GridSignal

ROLL_S = 10.0        # our sites' response: their 10-s measured mean over their pre-cap baseline


class Neighbourhood:
    def __init__(self, tl: Timeline, executor, cfg: dict | None = None):
        self.tl, self.ex = tl, executor
        self.cfg = cfg if cfg is not None else (config.neighbourhood or {})
        dc = self.cfg.get("data_centers") or {}
        n, (lo, hi) = int(dc.get("count", 0)), dc.get("size_kw", [0, 0])
        self.dc_sizes = [lo + (hi - lo) * i / (n - 1) for i in range(n)] if n > 1 else [float(lo)] * n
        self.flex = float(dc.get("flexible_share", 0.0))
        self.limit = float(self.cfg.get("line_limit_kw", 0))
        self.scenario_start: float | None = None
        self.cap_id: str | None = None
        self.cap_baseline_w: float | None = None
        self.pending_cap: CapEvent | None = None      # the utility's call, handed to the real dispatcher
        self.pending_withdraw: str | None = None      # a call to take back (replay stopped or finished)
        self.nothing_to_shed = False
        self._warned_no_baseline = False
        self.diesel_kwh = 0.0
        self.diesel_off_kwh = 0.0
        self.last: dict | None = None
        self.history: deque[dict] = deque(maxlen=900)
        self._last_t: float | None = None
        self._last_log = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.cfg) and self.limit > 0

    # ------------------------------------------------------------------ the simulated clock
    def scenario(self) -> dict:
        return self.cfg.get("scenario") or {}

    def running(self, now: float) -> bool:
        s = self.scenario()
        return self.scenario_start is not None and now - self.scenario_start < float(s.get("seconds", 0))

    def hour(self, now: float) -> float:
        """The simulated hour of day: replayed during the scenario, else the wall clock in the ISO's time zone."""
        if self.running(now):
            h0, h1 = self.scenario()["hours"]
            return h0 + (h1 - h0) * (now - self.scenario_start) / float(self.scenario()["seconds"])
        day = self._forecast_day(self.ex.signal, now)
        d = datetime.fromtimestamp(now, tz=day[0][0].tzinfo) if day else datetime.fromtimestamp(now)
        return d.hour + d.minute / 60 + d.second / 3600

    @staticmethod
    def _forecast_day(sig: GridSignal | None, now: float) -> list[tuple[datetime, float]]:
        """Today's points of the ISO's load forecast, in the ISO's time zone. ERCOT's forecast covers seven days
        (supervisor issue 13): hours repeat across days, so only today's are used."""
        if not sig or not sig.load_forecast:
            return []
        pts = sorted((t if isinstance(t, datetime) else datetime.fromisoformat(str(t)), float(mw)) for t, mw in sig.load_forecast)
        tz = pts[0][0].tzinfo
        today = datetime.fromtimestamp(now, tz=tz).date()
        day = [(t.astimezone(tz), mw) for t, mw in pts if t.astimezone(tz).date() == today]
        return day or [(t, mw) for t, mw in pts if t.date() == pts[0][0].date()]

    def sim_hours_per_s(self, now: float) -> float:
        if self.running(now):
            h0, h1 = self.scenario()["hours"]
            return (h1 - h0) / float(self.scenario()["seconds"])
        return 1 / 3600

    # ------------------------------------------------------------------ the parts of the line
    def homes_kw(self, hour: float, sig: GridSignal | None, now: float | None = None) -> float | None:
        """Today's real forecast at `hour`, its lowest hour mapped to homes_offices_kw[0] and its peak to [1]."""
        pts = self._forecast_day(sig, time.time() if now is None else now)
        if not pts:
            return None
        hours = [p[0].hour + p[0].minute / 60 for p in pts]
        mws = [p[1] for p in pts]
        i = bisect_right(hours, hour)
        if i == 0:
            mw = mws[0]
        elif i >= len(hours):
            mw = mws[-1]
        else:
            h0, h1, m0, m1 = hours[i - 1], hours[i], mws[i - 1], mws[i]
            mw = m0 + (m1 - m0) * (hour - h0) / (h1 - h0)
        lo, hi = self.cfg["homes_offices_kw"]
        span = max(mws) - min(mws)
        return float(hi) if span <= 0 else lo + (hi - lo) * (mw - min(mws)) / span

    def solar_kw(self, hour: float) -> float:
        rise, fall = self.cfg.get("solar_day", [6.5, 18.5])
        if not rise < hour < fall:
            return 0.0
        return float(self.cfg.get("solar_kw", 0)) * math.sin(math.pi * (hour - rise) / (fall - rise))

    def response(self, now: float) -> tuple[float, float | None]:
        """Our sites' measured response: 10-s mean of measured watts over their pre-cap baseline (1.0 = as usual).
        Only when our sites had flexible load running at the call: a baseline within `min_flexible_w` of the idle
        floor is meter noise (Krish K1 #3), so the simulated data centers hold and the page says so."""
        xs = [w for t, w in self.ex.power if t > now - ROLL_S]
        mean = sum(xs) / len(xs) if xs else None
        idle = getattr(getattr(self.ex, "cal", None), "idle_w", 0.0) or 0.0
        self.nothing_to_shed = bool(self.cap_baseline_w is not None and
                                    self.cap_baseline_w - idle < float(self.cfg.get("min_flexible_w", 3.0)))
        if self.cap_baseline_w and mean is not None and not self.nothing_to_shed:
            return max(0.0, min(1.5, mean / self.cap_baseline_w)), mean
        return 1.0, mean

    def dc_kw(self, r: float) -> float:
        return sum(size * (1 - self.flex + self.flex * r) for size in self.dc_sizes)

    # ------------------------------------------------------------------ one second
    def tick(self, now: float | None = None) -> dict | None:
        if not self.enabled:
            return None
        now = time.time() if now is None else now
        running = self.running(now)
        if self.scenario_start is not None and not running:
            self.stop(now, finished=True)
        hour = self.hour(now)
        homes = self.homes_kw(hour, self.ex.signal, now)
        solar = self.solar_kw(hour)
        r, ours_w = self.response(now)
        ours_kw = (ours_w or 0.0) / 1000
        dc = self.dc_kw(r)
        demand = (homes or 0.0) + dc + ours_kw - solar
        loading = 100 * demand / self.limit
        if running and self.cap_id is None and homes is not None and loading >= float(self.cfg.get("cap_trigger_pct", 95)):
            self._call_for_cut(now, homes, solar, ours_kw)
        diesel = max(0.0, min(float(self.cfg.get("diesel_kw", 0)), demand - self.limit))
        demand_off = (homes or 0.0) + self.dc_kw(1.0) + ours_kw - solar
        diesel_off = max(0.0, min(float(self.cfg.get("diesel_kw", 0)), demand_off - self.limit))
        if self._last_t is not None and running:
            dt_h = (now - self._last_t) * self.sim_hours_per_s(now)
            self.diesel_kwh += diesel * dt_h
            self.diesel_off_kwh += diesel_off * dt_h
        self._last_t = now
        state = {"t": now, "simulated": True, "scenario": self.scenario().get("name") if running else None,
                 "sim_hour": hour, "homes_kw": homes, "solar_kw": solar, "dc_kw": dc, "dc_count": len(self.dc_sizes),
                 "dc_flexible_share": self.flex, "response": r, "ours_w": ours_w, "line_kw": demand - diesel,
                 "demand_kw": demand, "limit_kw": self.limit, "loading_pct": loading, "diesel_kw": diesel,
                 "diesel_kwh": self.diesel_kwh, "diesel_off_kwh": self.diesel_off_kwh, "cap_id": self.cap_id,
                 "cap_baseline_w": self.cap_baseline_w, "nothing_to_shed": self.nothing_to_shed,
                 "inputs": "homes: shape of today's ISO load forecast; data centers: our sites' measured response"}
        self.last = state
        self.history.append(state)
        if running or now - self._last_log >= 10:
            self._last_log = now
            self.tl.log("neighbourhood", **state)
        return state

    def _call_for_cut(self, now: float, homes: float, solar: float, ours_kw: float) -> None:
        """The utility's call: a % cut for the data centers, sized for the worst loading still ahead in the
        replay (the utility knows the forecast; Krish K1 #2: sized for the moment, the line still peaked at 111 %)
        so that it lands cap_margin_pct under the limit at that worst point."""
        target = self.limit * (1 - float(self.cfg.get("cap_margin_pct", 8)) / 100)
        flex_total = sum(self.dc_sizes) * self.flex
        h1 = self.scenario()["hours"][1]
        ahead = [self.hour(now) + k * (h1 - self.hour(now)) / 50 for k in range(51)]
        net = [(self.homes_kw(h, self.ex.signal, now) or homes) - self.solar_kw(h) for h in ahead]
        worst = max([homes - solar] + net)
        fixed = worst + ours_kw + sum(self.dc_sizes) * (1 - self.flex)
        r_needed = (target - fixed) / flex_total if flex_total else 0.0
        pct = max(10.0, min(95.0, 100 * (1 - r_needed)))
        base = self.ex.baseline_w()
        if base is None:
            if not self._warned_no_baseline:              # once per replay, not every second (K1 #8)
                self._warned_no_baseline = True
                self.tl.log("note", msg="neighbourhood: the line needs a cut but our sites have no 60-s baseline yet",
                            simulated=True)
            return
        remaining = float(self.scenario()["seconds"]) - (now - self.scenario_start)
        ev = CapEvent(source="simulated", start=datetime.fromtimestamp(now).astimezone(), duration_s=int(remaining + 30),
                      target_pct=round(pct, 1),
                      reason=f"simulated neighbourhood line at {100 * (homes + self.dc_kw(1.0) + ours_kw - solar) / self.limit:.0f}% "
                             f"of its limit: cut the data centers' load {pct:.0f}%")
        self.cap_id, self.cap_baseline_w = ev.id, base
        self.pending_cap = ev

    # ------------------------------------------------------------------ control
    def start(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        if self.cap_id:                                   # a call from an earlier replay is still in force
            self.pending_withdraw = self.cap_id
        self.scenario_start, self.cap_id, self.cap_baseline_w = now, None, None
        self._warned_no_baseline = False
        self.diesel_kwh = self.diesel_off_kwh = 0.0
        self._last_t = None
        self.tl.log("note", msg=f"neighbourhood: {self.scenario().get('name', 'scenario')} replay started (simulated)",
                    simulated=True, hours=self.scenario().get("hours"), seconds=self.scenario().get("seconds"))
        return {"running": True, "scenario": self.scenario()}

    def stop(self, now: float | None = None, finished: bool = False) -> dict:
        now = time.time() if now is None else now
        if self.scenario_start is not None:
            self.tl.log("note", msg=f"neighbourhood: replay {'finished' if finished else 'stopped'} (simulated)",
                        simulated=True, diesel_kwh=self.diesel_kwh, diesel_off_kwh=self.diesel_off_kwh)
            if self.cap_id:                               # take back its call (K1 #6)
                self.pending_withdraw = self.cap_id
        self.scenario_start = None
        return {"running": False}

    def summary(self) -> dict:
        """For the snapshot: the configuration a page needs to draw the line, and the latest state."""
        return {"enabled": self.enabled, "limit_kw": self.limit, "dc_sizes_kw": self.dc_sizes,
                "dc_flexible_share": self.flex, "solar_kw": self.cfg.get("solar_kw"),
                "diesel_kw": self.cfg.get("diesel_kw"), "scenario": self.scenario(), "last": self.last}
