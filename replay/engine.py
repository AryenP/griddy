"""Replay a real grid emergency through the live software (config/events.yaml; Aryen, Sat 15:40).

The grid's side is REAL and recorded: hourly demand served, the operator's own day-ahead forecast and generation by
fuel (U.S. EIA Form EIA-930, docs/evidence/events/<id>.csv), and every alert at the time the official report gives.
Brownout's side is LIVE: the replay hands each alert to the real dispatcher as a cap on this Mac's sites at the
moment it was issued, and the Mac's measured watts are what they are.

  - At start: the warnings issued days before (operator notices, Flex Alerts) and Brownout's own flag, when the
    operator's day-ahead forecast for the window is above its record before the event. The warning's cut shifts
    deferrable work off our sites first.
  - At each emergency's real time (mapped onto `replay_seconds`): a deeper cut, below the baseline measured just
    before the replay started.
  - An `end` alert withdraws the emergency cut; the end of the replay withdraws everything.
  - Scale: our sites' measured cut, as a share of their baseline, applied to the operator's flexible load (a cited
    figure, or 1 GW as a stated unit) and set against what the event shed and whom it left in the dark.
"""
from __future__ import annotations

import time
from collections import deque
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from core import config
from core.timeline import Timeline
from core.types import CapEvent

ROLL_S = 10.0          # our sites' response: their 10-s measured mean
BASELINE_S = 60.0      # over the measured mean in the 60 s before the replay
ROOT = Path(__file__).resolve().parents[1]
# EIA-930 fuel names -> config/isos.yaml emission factor rows (petroleum has no row there: the "Other" default)
EIA_FUELS = {"Coal": "Coal", "Natural Gas": "Natural Gas", "Nuclear": "Nuclear", "Solar": "Solar", "Wind": "Wind",
             "Hydropower and Pumped Storage": "Large Hydro", "All Petroleum Products": "Other", "Other Fuel Sources": "Other"}


def _local(s: str, tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(str(s)).replace(tzinfo=tz)


def load_series(ev: dict) -> pd.DataFrame:
    """The event's EIA-930 hours, indexed by local hour-ending time, with carbon intensity from the fuel mix."""
    df = pd.read_csv(ROOT / ev["data"], comment="#")
    tz = ZoneInfo(ev["timezone"])
    df.index = pd.to_datetime(df["utc_end"], utc=True).dt.tz_convert(tz)
    factors = config.isos["emission_factors_gco2_per_kwh"]
    gen = df[[c for c in EIA_FUELS if c in df.columns]].clip(lower=0).fillna(0)
    weights = pd.Series({c: factors[EIA_FUELS[c]] for c in gen.columns})
    total = gen.sum(axis=1)
    df["carbon_g_kwh"] = (gen * weights).sum(axis=1) / total.where(total > 0)
    return df[["demand_forecast_mw", "demand_mw", "carbon_g_kwh"]]


def at(series: pd.DataFrame, t: datetime) -> dict:
    """Linear between hour-ending points; outside the data, the nearest point."""
    idx = series.index
    i = idx.searchsorted(pd.Timestamp(t))
    if i <= 0:
        row = series.iloc[0]
    elif i >= len(idx):
        row = series.iloc[-1]
    else:
        t0, t1 = idx[i - 1], idx[i]
        f = (pd.Timestamp(t) - t0) / (t1 - t0)
        row = series.iloc[i - 1] * (1 - f) + series.iloc[i] * f
    return {k: (None if pd.isna(v) else float(v)) for k, v in row.items()}


class Replay:
    def __init__(self, tl: Timeline, executor, cfg: dict | None = None):
        self.tl, self.ex = tl, executor
        self.cfg = cfg if cfg is not None else (config.events or {})
        self.events = {e["id"]: e for e in self.cfg.get("events", [])}
        self.seconds = float(self.cfg.get("replay_seconds", 120))
        self.series: dict[str, pd.DataFrame] = {}
        self.event: dict | None = None
        self.start_t: float | None = None
        self.baseline_w: float | None = None
        self.fired: list[dict] = []
        self.caps: dict[str, str] = {}               # kind of cut -> CapEvent id in force
        self.asked: dict[str, float] = {}             # kind of cut -> % the alert asked of our sites
        self.pending_caps: list[CapEvent] = []        # handed to the real dispatcher by the runtime
        self.pending_withdraw: list[str] = []
        self.nothing_to_shed = False
        self.last: dict | None = None
        self.history: deque[dict] = deque(maxlen=600)

    @property
    def enabled(self) -> bool:
        return bool(self.events)

    def running(self, now: float) -> bool:
        return self.event is not None and self.start_t is not None and now - self.start_t < self.seconds

    def data(self, eid: str) -> pd.DataFrame:
        if eid not in self.series:
            self.series[eid] = load_series(self.events[eid])
        return self.series[eid]

    # ------------------------------------------------------------------ the replayed clock
    def window(self, ev: dict) -> tuple[datetime, datetime]:
        tz = ZoneInfo(ev["timezone"])
        return _local(ev["window"][0], tz), _local(ev["window"][1], tz)

    def sim_time(self, now: float) -> datetime:
        w0, w1 = self.window(self.event)
        f = min(1.0, max(0.0, (now - self.start_t) / self.seconds))
        return w0 + (w1 - w0) * f

    def real_s(self, ev: dict, t: datetime) -> float:
        """Seconds into the replay at which real time `t` falls."""
        w0, w1 = self.window(ev)
        return self.seconds * (t - w0).total_seconds() / (w1 - w0).total_seconds()

    # ------------------------------------------------------------------ catalog for the pages
    def catalog(self) -> list[dict]:
        out = []
        for ev in self.events.values():
            s = self.data(ev["id"])
            w0, w1 = self.window(ev)
            win = s[(s.index >= pd.Timestamp(w0)) & (s.index <= pd.Timestamp(w1) + pd.Timedelta(hours=1))]
            out.append({**{k: ev.get(k) for k in ("id", "title", "when", "iso", "ba", "timezone", "impact", "shed_mw",
                                                   "people_out", "people_unit", "flexible_mw", "flexible_source",
                                                   "record_mw", "record_source", "report_url")},
                        "window": [w0.isoformat(), w1.isoformat()],
                        "alerts": self.alerts(ev),
                        "series": [[t.isoformat(), r.demand_mw, r.demand_forecast_mw] for t, r in win.iterrows()],
                        "data_source": f"U.S. EIA Form EIA-930, balancing authority {ev['ba']} ({ev['data']})"})
        return out

    def alerts(self, ev: dict) -> list[dict]:
        """The cited alerts and Brownout's own flag, in the order they happened: warnings days before first."""
        out = [self._alert_view(ev, a) for a in ev.get("alerts", [])] + self._flag(ev)
        return sorted(out, key=lambda a: (not a["before_window"], a.get("day") or "~", a["replay_s"]))   # the flag: after dated notices

    def _alert_view(self, ev: dict, a: dict) -> dict:
        tz = ZoneInfo(ev["timezone"])
        if "at" in a:
            t = _local(a["at"], tz)
            return {**a, "at": t.isoformat(), "replay_s": max(0.0, self.real_s(ev, t)), "before_window": False}
        return {**a, "day": str(a["day"]), "replay_s": 0.0, "before_window": True}

    def _flag(self, ev: dict) -> list[dict]:
        """Brownout's own warning: the operator's day-ahead forecast for the window above its record before the event."""
        rec = ev.get("record_mw")
        if not rec:
            return []
        s = self.data(ev["id"])
        w0, w1 = self.window(ev)
        win = s[(s.index > pd.Timestamp(w0)) & (s.index <= pd.Timestamp(w1))]
        peak_t = win["demand_forecast_mw"].idxmax()
        peak = float(win["demand_forecast_mw"].max())
        if peak <= rec:
            return []
        return [{"kind": "brownout", "replay_s": 0.0, "before_window": True, "at": None,
                 "label": f"Brownout's flag: the day-ahead forecast peaks at {peak:,.0f} MW ({peak_t:%a %H:%M}), above the "
                          f"{rec:,} MW record before this event",
                 "source": f"forecast: EIA-930 ({ev['ba']}); record: {ev['record_source']}"}]

    # ------------------------------------------------------------------ start / stop
    def start(self, eid: str, now: float | None = None) -> dict:
        if eid not in self.events:
            raise KeyError(eid)
        now = time.time() if now is None else now
        if self.event is not None:
            self.stop(now)
        self.event, self.start_t, self.fired = self.events[eid], now, []
        xs = [w for t, w in self.ex.power if now - BASELINE_S <= t <= now]
        self.baseline_w = sum(xs) / len(xs) if xs else None
        idle = getattr(getattr(self.ex, "cal", None), "idle_w", 0.0) or 0.0
        self.nothing_to_shed = self.baseline_w is not None and self.baseline_w - idle < float(self.cfg.get("min_flexible_w", 3.0))
        self.tl.log("note", msg=f"replay: {self.event['title']} ({self.event['when']}) started", replay=eid,
                    baseline_w=self.baseline_w, nothing_to_shed=self.nothing_to_shed)
        return {"event": eid, "baseline_w": self.baseline_w, "seconds": self.seconds, "nothing_to_shed": self.nothing_to_shed}

    def stop(self, now: float | None = None, finished: bool = False) -> dict:
        if self.event is not None:
            self.pending_withdraw += list(self.caps.values())
            self.tl.log("note", msg=f"replay: {self.event['title']} {'finished' if finished else 'stopped'}",
                        replay=self.event["id"], withdrawn=list(self.caps.values()))
        eid = self.event["id"] if self.event else None
        self.event, self.start_t, self.caps, self.asked = None, None, {}, {}
        return {"event": eid, "stopped": True}

    def _cut(self, now: float, a: dict, kind: str) -> None:
        """Hand the alert's cut to the real dispatcher, below the baseline measured before the replay."""
        if self.baseline_w is None or self.nothing_to_shed or not a.get("cut_pct"):
            return
        target = self.baseline_w * (1 - float(a["cut_pct"]) / 100)
        remaining = max(5.0, self.seconds - (now - self.start_t)) + 5.0
        ev = CapEvent(source="replay", start=datetime.fromtimestamp(now).astimezone(), duration_s=int(remaining),
                      target_w=target, target_pct=float(a["cut_pct"]),
                      reason=f"replay of {self.event['title']} ({self.event['when']}): {a['label']}", raw=a.get("source", ""))
        if kind in self.caps:
            self.pending_withdraw.append(self.caps[kind])
        self.caps[kind] = ev.id
        self.asked[kind] = float(a["cut_pct"])
        self.pending_caps.append(ev)

    # ------------------------------------------------------------------ one second
    def tick(self, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        if self.event is None:
            return None
        if not self.running(now):
            self.stop(now, finished=True)
            return None
        ev, s_into = self.event, now - self.start_t
        for a in self.alerts(ev):
            key = (a["label"], a.get("at") or a.get("day"))
            if a["replay_s"] <= s_into and key not in {(f["label"], f.get("at") or f.get("day")) for f in self.fired}:
                self.fired.append(a)
                if a["kind"] in ("warning", "emergency"):
                    self._cut(now, a, a["kind"])
                elif a["kind"] == "end" and "emergency" in self.caps:
                    self.pending_withdraw.append(self.caps.pop("emergency"))
                    self.asked.pop("emergency", None)
                self.tl.log("note", msg=f"replay alert: {a['label']}", replay=ev["id"], alert=a)
        t = self.sim_time(now)
        grid = at(self.data(ev["id"]), t)
        xs = [w for tt, w in self.ex.power if tt > now - ROLL_S]
        ours = sum(xs) / len(xs) if xs else None
        cut = (1 - ours / self.baseline_w) if ours is not None and self.baseline_w and self.caps else None
        state = {"t": now, "event": ev["id"], "title": ev["title"], "sim_time": t.isoformat(),
                 "progress": min(1.0, s_into / self.seconds), "demand_mw": grid["demand_mw"],
                 "forecast_mw": grid["demand_forecast_mw"],
                 "gap_mw": (grid["demand_forecast_mw"] - grid["demand_mw"]) if grid["demand_mw"] is not None and grid["demand_forecast_mw"] is not None else None,
                 "carbon_g_kwh": grid["carbon_g_kwh"], "fired": [f["label"] for f in self.fired],
                 "cut_kinds": sorted(self.caps), "baseline_w": self.baseline_w, "ours_w": ours,
                 "measured_cut_pct": None if cut is None else 100 * cut, "nothing_to_shed": self.nothing_to_shed,
                 "asked_cut_pct": max(self.asked.values()) if self.asked else None,
                 "scale": self.scale(ev, cut, max(self.asked.values()) / 100 if self.asked else None)}
        self.last = state
        self.history.append(state)
        self.tl.log("replay", **state)
        return state

    @staticmethod
    def scale(ev: dict, cut: float | None, asked: float | None = None) -> dict | None:
        """The cut the alert asked of our sites, as far as they measurably delivered it (the smaller of the two),
        applied to the operator's flexible load and set against what the event shed. Shedding more than asked on
        this Mac (the solver may pause a job outright) is not credited to the grid."""
        if cut is None or cut <= 0:
            return None
        share = min(1.0, cut, asked if asked is not None else cut)
        freed = float(ev["flexible_mw"]) * share
        out = {"freed_mw": freed, "share_pct": 100 * share, "flexible_mw": ev["flexible_mw"], "flexible_source": ev["flexible_source"],
               "share_of_shed_pct": 100 * freed / ev["shed_mw"] if ev.get("shed_mw") else None, "people": None}
        if ev.get("people_out") and ev.get("shed_mw"):
            out["people"] = round(ev["people_out"] / ev["shed_mw"] * freed)
            out["people_unit"] = ev.get("people_unit", "people")
        return out

    def summary(self) -> dict:
        return {"enabled": self.enabled, "seconds": self.seconds, "active": self.event["id"] if self.event else None,
                "events": [{"id": e["id"], "title": e["title"], "when": e["when"], "iso": e["iso"]} for e in self.events.values()],
                "last": self.last}
