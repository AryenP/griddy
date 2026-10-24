"""The Mac's side of the fleet: laptops that join as extra, measured sites (each runs fleet/agent.py).

A laptop counts as online when it is listed in config/fleet.yaml, has sent a fresh battery reading (within
`stale_s`) and has been calibrated on itself (`python fleet/agent.py --calibrate`). Online laptops add:
  - their measured watts to the machine total the cap is judged on (logged as `fleet_power` events, the Mac's
    own `power` events unchanged), so the executor, the reporter and the dashboard see the fleet's total;
  - their idle draw and their job (calibrated watts and rate) to the solver's inputs;
  - a run/pause for their job, returned in reply to each heartbeat.
With no laptop online nothing here changes a number: Brownout is one site, exactly as before.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from core import config
from core.timeline import Timeline
from core.types import Calibration, DevicePower, Job, PowerReading

CAL_PATH = Path("runs") / "fleet-calibration.json"


class Fleet:
    def __init__(self, tl: Timeline, cfg: dict | None = None, cal_path: str | Path = CAL_PATH):
        self.tl = tl
        self.cfg = cfg if cfg is not None else (config.fleet or {})
        self.sites: dict[str, dict] = {s["id"]: s for s in self.cfg.get("sites") or []}
        self.stale_s = float(self.cfg.get("stale_s", 5))
        self.cal_path = Path(cal_path)
        self.cal: dict[str, dict] = self._load_cal()
        self.beats: dict[str, dict] = {}
        self.run: dict[str, bool] = {}
        self._members: frozenset[str] = frozenset()

    def _load_cal(self) -> dict[str, dict]:
        try:
            return json.loads(self.cal_path.read_text())
        except (OSError, ValueError):
            return {}

    # ------------------------------------------------------------------ from the laptops
    def beat(self, site: str, body: dict, now: float | None = None) -> dict:
        """A laptop's heartbeat: its latest battery reading and job progress. The reply is its plan."""
        self.beats[site] = {**body, "received": time.time() if now is None else now}
        return {"site": site, "run": bool(self.run.get(site, False))}

    def calibrate(self, site: str, body: dict) -> dict:
        self.cal[site] = body
        self.cal_path.parent.mkdir(parents=True, exist_ok=True)
        self.cal_path.write_text(json.dumps(self.cal, indent=1))
        self.tl.log("note", msg=f"fleet calibration stored for {site}", site=site,
                    **{k: body.get(k) for k in ("idle_w", "delta_w", "rate_mb_s", "machine", "meter")})
        return {"site": site, "status": "stored"}

    # ------------------------------------------------------------------ state
    def watts(self, site: str, now: float) -> float | None:
        b = self.beats.get(site)
        if not b or b.get("watts") is None or now - b["received"] > self.stale_s:
            return None
        return float(b["watts"])

    def online(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        return [s for s in self.sites if s in self.cal and self.watts(s, now) is not None]

    def membership_changed(self, now: float | None = None) -> str | None:
        """Which laptops joined or left since the last call (a reason to re-solve), else None."""
        m = frozenset(self.online(now))
        if m == self._members:
            return None
        joined, left = sorted(m - self._members), sorted(self._members - m)
        self._members = m
        return ", ".join([f"{s} joined" for s in joined] + [f"{s} left" for s in left])

    def status(self, now: float | None = None) -> list[dict]:
        """Every configured laptop, for the snapshot: online or why not, its watts, its plan."""
        now = time.time() if now is None else now
        out = []
        for s, spec in self.sites.items():
            b = self.beats.get(s) or {}
            w = self.watts(s, now)
            if w is not None:
                why = "online" if s in self.cal else "not calibrated: run fleet/agent.py --calibrate"
            elif not b:
                why = "no heartbeat yet"
            elif now - b["received"] > self.stale_s:
                why = f"no heartbeat for over {self.stale_s:.0f} s"
            else:
                why = b.get("meter_note") or "no battery reading"
            out.append({"id": s, "name": spec.get("name", s), "owner": spec.get("owner"), "status": why,
                        "watts": w, "run": self.run.get(s, False), "running": b.get("running"),
                        "done_mb": b.get("done_mb"), "rate_mb_s": b.get("rate_mb_s"),
                        "machine": b.get("machine") or (self.cal.get(s) or {}).get("machine"),
                        "calibration": self.cal.get(s), "last_beat": b.get("received")})
        return out

    # ------------------------------------------------------------------ to the dispatcher
    def combine(self, r: PowerReading) -> PowerReading:
        """The Mac's measured reading plus every online laptop's fresh battery reading."""
        online = self.online(r.t)
        if not online:
            return r
        sites = {s: self.watts(s, r.t) for s in online}
        total = r.combined_w + sum(sites.values())
        self.tl.log("fleet_power", t=r.t, mac_w=r.combined_w, sites=sites, combined_w=total)
        return r.model_copy(update={"combined_w": total})

    def jobs(self, now: float | None = None) -> list[Job]:
        """One job per online laptop: its remaining backlog over its own measured rate."""
        spec = self.cfg.get("job") or {}
        out = []
        for s in self.online(now):
            rate = float(self.cal[s].get("rate_mb_s") or 0)
            if rate <= 0:
                continue
            left = max(0.0, float(spec.get("backlog_mb", 0)) - float(self.beats[s].get("done_mb") or 0))
            out.append(Job(id=s, kind=spec.get("kind", "droppable"), owner=self.sites[s].get("owner") or spec.get("owner", ""),
                           priority=int(spec.get("priority", 3)), device="cpu", interruptible=True,
                           measured_w=self.cal[s].get("delta_w"), required_runtime_min=math.ceil(left / rate / 60),
                           state="done" if left <= 0 else "pending",
                           progress={"done": self.beats[s].get("done_mb"), "total": spec.get("backlog_mb")}))
        return out

    def calibration(self, base: Calibration, now: float | None = None) -> Calibration:
        """The Mac's calibration plus each online laptop's idle draw and job (CPU) watts and rate."""
        online = [s for s in self.online(now) if float(self.cal[s].get("rate_mb_s") or 0) > 0]
        if not online:
            return base
        jobs = dict(base.jobs)
        for s in online:
            c = self.cal[s]
            jobs[s] = {"cpu": DevicePower(delta_w=float(c["delta_w"]), rate=float(c["rate_mb_s"]),
                                          samples=int(sum(c.get("samples") or [0])))}
        return base.model_copy(update={"idle_w": base.idle_w + sum(float(self.cal[s]["idle_w"]) for s in online),
                                       "jobs": jobs})

    def set_run(self, site: str, run: bool) -> None:
        self.run[site] = run
