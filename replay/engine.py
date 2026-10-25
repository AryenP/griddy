"""Replay a real grid emergency through the live software (config/events.yaml; Aryen, Sat 15:40).

The grid's side is REAL and recorded: hourly demand served, the operator's own day-ahead forecast and generation by
fuel (U.S. EIA Form EIA-930), fetched live from api.eia.gov when the judge presses play (replay/eia.py; the evidence
copy in docs/evidence/events/<id>.csv only if the API cannot be reached, and the page says so), and every alert at the
time the official report gives. Brownout's side is LIVE: the replay hands each alert to the real dispatcher as a cap on
this Mac's sites at the moment it was issued, and the Mac's measured watts are what they are.

Nothing here knows what comes next (Aryen, Sat evening: "if it's trained on this data and is just replaying, it defeats
the whole purpose"). Brownout is not trained on any event: the solver is deterministic and sees only its inputs. At
each moment of the replayed clock the software sees the hours that have ENDED (never a later hour), and day-ahead
forecasts only for the hours of the current day (the operator published them the day before). Brownout's own flag is
computed the same way, at the first moment it could have been. tests/test_replay.py deletes the future and checks
that nothing changes.

  - At start: the warnings issued days before (operator notices, Flex Alerts). Brownout's own flag fires at the first
    moment a published day-ahead forecast for the rest of the day is above the operator's record before the event,
    and asks our sites for the warning cut itself. The warning's cut shifts deferrable work off our sites first.
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
from replay import eia

ROLL_S = 10.0          # our sites' response: their 10-s measured mean
BASELINE_S = 20.0      # over the measured mean in the 20 s before the replay (a job started just before still counts)
ROOT = Path(__file__).resolve().parents[1]
# EIA-930 fuel names -> config/isos.yaml emission factor rows (petroleum has no row there: the "Other" default)
EIA_FUELS = {"Coal": "Coal", "Natural Gas": "Natural Gas", "Nuclear": "Nuclear", "Solar": "Solar", "Wind": "Wind",
             "Hydropower and Pumped Storage": "Large Hydro", "All Petroleum Products": "Other", "Other Fuel Sources": "Other"}


def _local(s: str, tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(str(s)).replace(tzinfo=tz)


def load_series(ev: dict) -> pd.DataFrame:
    """The evidence copy of the event's EIA-930 hours (docs/evidence/events/<id>.csv)."""
    return series_from(pd.read_csv(ROOT / ev["data"], comment="#"), ev)


def series_from(df: pd.DataFrame, ev: dict) -> pd.DataFrame:
    """EIA-930 hours, indexed by local hour-ending time, with carbon intensity from the fuel mix."""
    tz = ZoneInfo(ev["timezone"])
    df.index = pd.to_datetime(df["utc_end"], utc=True).dt.tz_convert(tz)
    factors = config.isos["emission_factors_gco2_per_kwh"]
    gen = df[[c for c in EIA_FUELS if c in df.columns]].clip(lower=0).fillna(0)
    weights = pd.Series({c: factors[EIA_FUELS[c]] for c in gen.columns})
    total = gen.sum(axis=1)
    df["carbon_g_kwh"] = (gen * weights).sum(axis=1) / total.where(total > 0)
    return pd.concat([df[["demand_forecast_mw", "demand_mw", "carbon_g_kwh"]], gen.add_prefix("mix:")], axis=1)


def at(series: pd.DataFrame, t: datetime) -> dict:
    """What the operator had published by `t`: the last hour that has ended (hour-ending at or before t), never a later
    one. Before the first hour, nothing."""
    i = series.index.searchsorted(pd.Timestamp(t), side="right")
    if i <= 0:
        return {k: None for k in series.columns} | {"hour_ending": None}
    row = series.iloc[i - 1]
    return {k: (None if pd.isna(v) else float(v)) for k, v in row.items()} | {"hour_ending": series.index[i - 1].isoformat()}


class Replay:
    def __init__(self, tl: Timeline, executor, cfg: dict | None = None):
        self.tl, self.ex = tl, executor
        self.cfg = cfg if cfg is not None else (config.events or {})
        self.events = {e["id"]: e for e in self.cfg.get("events", [])}
        self.seconds = float(self.cfg.get("replay_seconds", 120))
        self.series: dict[str, pd.DataFrame] = {}
        self.provenance: dict[str, dict] = {}         # where each event's hours came from: live, or the evidence copy
        self.cache = eia.Cache(float(self.cfg.get("refetch_s", 600)))
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
            self.provenance[eid] = {"source": "evidence copy", "url": self.events[eid]["data"], "why": "not fetched yet"}
        return self.series[eid]

    def prepare(self, eid: str) -> dict:
        """Fetch the event's hours live from api.eia.gov (blocking: the API route runs it in a thread). If the API
        cannot be reached, the evidence copy, and the reason."""
        ev = self.events[eid]
        evidence = pd.read_csv(ROOT / ev["data"], comment="#")
        try:
            df, meta = self.cache.get(ev)
            meta = {**meta, "max_diff_mw": eia.agreement(df, evidence)}
        except Exception as e:                       # network down, rate limit: say so, and run on the evidence copy
            df, meta = evidence, {"source": "evidence copy", "url": ev["data"], "why": f"api.eia.gov: {e!r}"[:200]}
        self.series[eid] = series_from(df, ev)
        self.provenance[eid] = meta
        self.tl.log("note", msg=f"replay data for {eid}: {meta['source']}", replay=eid, data=meta)
        return meta

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
            out.append({**{k: ev.get(k) for k in ("id", "title", "when", "iso", "region", "ba", "timezone", "impact", "shed_mw",
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
        """Brownout's own warning, at the first moment it could have been raised: a published day-ahead forecast for
        the rest of the current day (published the day before) above the operator's record before the event. Checked
        at the window's start and at each local midnight in it, when the next day's forecasts count as published."""
        rec = ev.get("record_mw")
        if not rec:
            return []
        fc = self.data(ev["id"])["demand_forecast_mw"].dropna()
        day = pd.Series((fc.index - pd.Timedelta(hours=1)).date, index=fc.index)   # hour-ending 00:00 belongs to the day before
        w0, w1 = self.window(ev)
        moments = [w0] + [datetime.combine(d, datetime.min.time(), w0.tzinfo)
                          for d in pd.date_range(w0.date(), w1.date())[1:].date]
        for m in moments:
            ahead = fc[(fc.index > pd.Timestamp(m)) & (day <= m.date())]
            if len(ahead) and float(ahead.max()) > rec:
                peak_t, peak = ahead.idxmax(), float(ahead.max())
                return [{"kind": "brownout", "replay_s": self.real_s(ev, m), "before_window": m == w0,
                         "at": None if m == w0 else m.isoformat(), "cut_pct": float(self.cfg.get("flag_cut_pct", 20)),
                         "label": f"Brownout's flag: the day-ahead forecast for {peak_t:%a %H:%M} is {peak:,.0f} MW, above the "
                                  f"{rec:,} MW record before this event. Our sites start shifting work now",
                         "source": f"forecast: EIA-930 ({ev['ba']}), published the day before; record: {ev['record_source']}"}]
        return []

    # ------------------------------------------------------------------ start / stop
    def start(self, eid: str, now: float | None = None) -> dict:
        if eid not in self.events:
            raise KeyError(eid)
        now = time.time() if now is None else now
        if self.event is not None:
            self.stop(now)
        self.event, self.start_t, self.fired = self.events[eid], now, []
        xs = [w for t, w in self.ex.power if now - float(self.cfg.get("baseline_s", BASELINE_S)) <= t <= now]
        self.baseline_w = sum(xs) / len(xs) if xs else None
        idle = getattr(getattr(self.ex, "cal", None), "idle_w", 0.0) or 0.0
        self.nothing_to_shed = self.baseline_w is not None and self.baseline_w - idle < float(self.cfg.get("min_flexible_w", 3.0))
        self.data(eid)
        self.tl.log("note", msg=f"replay: {self.event['title']} ({self.event['when']}) started", replay=eid,
                    baseline_w=self.baseline_w, nothing_to_shed=self.nothing_to_shed, data=self.provenance.get(eid))
        return {"event": eid, "baseline_w": self.baseline_w, "seconds": self.seconds, "nothing_to_shed": self.nothing_to_shed,
                "data": self.provenance.get(eid)}

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
                if a["kind"] in ("warning", "emergency", "brownout"):
                    self._cut(now, a, "emergency" if a["kind"] == "emergency" else "warning")
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
                 "hour_ending": grid["hour_ending"], "data": self.provenance.get(ev["id"]),
                 "progress": min(1.0, s_into / self.seconds), "demand_mw": grid["demand_mw"],
                 "forecast_mw": grid["demand_forecast_mw"],
                 "gap_mw": (grid["demand_forecast_mw"] - grid["demand_mw"]) if grid["demand_mw"] is not None and grid["demand_forecast_mw"] is not None else None,
                 "carbon_g_kwh": grid["carbon_g_kwh"],
                 "mix_mw": {k[4:]: v for k, v in grid.items() if k.startswith("mix:") and v is not None},
                 "fired": [f["label"] for f in self.fired],
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
