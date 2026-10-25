"""Griddy's automatic emergency response (Aryen, Sat 22:30: "it takes over automatically in an emergency to prevent
damages and casualties ... fix the plants and substations ... send repair crews").

When a part of the city's grid fails or overloads, Griddy acts in order, without waiting for anyone:
  1. isolate   cut the faulted part off (open its breakers), so a fault or a fire does not spread
  2. protect   island the hospitals onto the city's own central plants
  3. reroute   close a tie switch to a neighbouring feed and pick up what it can carry
  4. shed      free capacity from loads that can wait: AI work at data centers (REAL: this Mac's measured watts, through
               the real dispatcher; the owner is still asked before a deadline slips) and home EV charging (simulated)
  5. dispatch  send a repair crew (Fetch.ai agents bid on the work order, agent/channels/crews.py)
  6. restore   when the crew reports the repair, close the breakers and give everything back
Software cannot repair a transformer: the crew does, and Griddy keeps the lights on around the fault until then.

What is real and what is simulated is in config/networks.yaml and on every step: the map, the substation, the plants,
the lines, the hospitals and the streets are OpenStreetMap; the switching, the ratings, EV charging, rooftop solar and
the crews are simulated, because no public source lists the feeders and Griddy has no access to a utility's switches.
The grid's own numbers (a plant trip, a demand surge) are the replay's or the live feed's, as in replay/whatif.py.
Loads are shares of the square's normal load (1.0); a zone's share is its buildings' real floor volume.
"""
from __future__ import annotations

import itertools
import json
import re
import time
from datetime import datetime
from pathlib import Path

import yaml

from core.timeline import Timeline
from core.types import CapEvent
from response.network import ZONES, Network

KINDS = ("substation", "line", "ev_surge", "solar_backfeed", "demand_surge", "plant", "grid_emergency")
GRID_SHORT = ("plant", "grid_emergency")   # the whole grid is short: no neighbouring feed has spare
CREWED = ("substation", "line")
NO_CREW_S = 10.0                # no crew agent picked the order up by then: say so
SURGE_S = 90.0                  # how long an EV, solar or demand surge lasts in the demo
DONE_S = 8.0                    # the restored city stays on screen this long, then the incident closes
MAX_S = 900.0
SIM = "simulated"


def kind_for(target: str, cause: str = "") -> str:
    """Which incident a judge's broken part is (replay/whatif.py targets, agent/faults.py words)."""
    c = cause.lower()
    if re.search(r"\bevs?\b|electric (?:car|vehicle)|charg(?:er|ing)|plug(?:s|ged)? in", c):
        return "ev_surge"
    if re.search(r"backfeed|back-feed|rooftop|over-?voltage|solar (?:surge|export)|too much solar", c):
        return "solar_backfeed"
    if target == "hub":
        return "line" if re.search(r"\blines?\b|cable|pole|wire|tower|tree|transmission", c) else "substation"
    if target == "city":
        return "demand_surge"
    if target.startswith("plant:"):
        return "plant"
    if target in KINDS:
        return target
    raise KeyError(target)


class Response:
    def __init__(self, tl: Timeline, executor, replay, whatif, root: Path, cfg: dict | None = None):
        self.tl, self.ex, self.replay, self.whatif, self.root = tl, executor, replay, whatif, Path(root)
        self.cfg = cfg or {}
        self.nets = yaml.safe_load((self.root / "config/networks.yaml").read_text())["networks"]
        self._built: dict[str, Network] = {}
        self.inc: dict | None = None
        self.cap_id: str | None = None
        self.last: dict | None = None
        self._ids = itertools.count(1)

    def network(self, city_id: str = "houston") -> Network:
        if city_id not in self._built:
            m = json.loads((self.root / f"docs/evidence/city/{city_id}-map.json").read_text())
            self._built[city_id] = Network(city_id, m, self.nets[city_id])
        return self._built[city_id]

    # ------------------------------------------------------------------ start, crews, end
    def start(self, kind: str, now: float | None = None, cause: str = "", line: int = 0, trigger: str = "judge",
              label: str = "") -> dict:
        now = time.time() if now is None else now
        if kind not in KINDS:
            raise KeyError(kind)
        net = self.network()
        line = max(0, min(line, len(net.lines) - 1)) if net.lines else 0
        if kind == "line" and not net.lines:
            raise ValueError("no 138 kV line into the substation is mapped")
        self.end(now, "replaced by a new incident")
        g = self.whatif.last if self.whatif.last and self.whatif.active(now) else None
        mult = 1.0
        if kind == "ev_surge":
            mult = 1 + net.cfg["ev_surge_pct"] / 100
        elif kind == "demand_surge":
            if g and g.get("needed_before"):
                mult = g["needed_after"] / g["needed_before"]          # the grid's real surge, as a ratio
            else:
                mult = 1 + net.cfg["ev_surge_pct"] / 100
        what = {"substation": f"{net.substation['name']} fails: transformer fault",
                "line": f"{net.line_name(line)} into {net.substation['name']} goes down",
                "ev_surge": f"evening EV charging: the feeders jump to {mult:.0%} of normal ({SIM})",
                "solar_backfeed": f"midday rooftop solar pushes {net.cfg['solar_export_pct']} % back into feeders that take "
                                  f"{net.cfg['solar_limit_pct']} %: voltage runs high ({SIM})",
                "demand_surge": f"demand surges to {mult:.0%} of normal" + (" (the grid's real forecast peak)" if g else f" ({SIM})"),
                "plant": (g or {}).get("label", "a plant trips"),
                "grid_emergency": label or "the grid operator declares an emergency"}[kind]
        if cause:
            what = f"{what}. Cause, in the judge's words: {cause}"
        site = net.site_of(kind, line)
        self.inc = {"id": f"inc-{next(self._ids)}", "kind": kind, "t0": now, "what": what, "cause": cause, "line": line,
                    "trigger": trigger, "mult": mult, "site": {"x": site[0], "z": site[1]}, "grid": g,
                    "baseline_w": self._baseline(now), "order": None, "crew": None, "bids": [], "repaired_at": None,
                    "steps": [{"t": now, "step": "detect", "text": what, "kind": "recorded" if trigger == "replay" else "what-if"}]}
        self.tl.log("response", msg=f"incident: {what}", incident=self.inc["id"], incident_kind=kind, trigger=trigger)
        return self.tick(now)

    def _baseline(self, now: float) -> float | None:
        if self.replay.event is not None and self.replay.baseline_w:
            return self.replay.baseline_w
        xs = [w for t, w in self.ex.power if now - 20 <= t <= now]
        return sum(xs) / len(xs) if xs else None

    def open_orders(self) -> list[dict]:
        """Work orders no crew has taken yet (for agent/channels/crews.py, over loopback only)."""
        o = self.inc and self.inc["order"]
        return [o] if o and not self.inc["crew"] else []

    def crew_update(self, order_id: str, crew: str, status: str, eta_s: float | None = None,
                    bids: list | None = None, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        inc = self.inc
        if not inc or not inc["order"] or inc["order"]["id"] != order_id:
            raise KeyError(order_id)
        net = self.network()
        crews = {c["id"]: c for c in net.cfg["crews"]}
        if crew not in crews:
            raise KeyError(crew)
        if status not in ("assigned", "en_route", "on_site", "repaired"):
            raise ValueError(f"unknown status {status!r}")
        name = crews[crew]["name"]
        route = inc["order"]["routes"].get(crew, {})
        c = inc["crew"] or {"id": crew, "name": name, "route": route.get("pts", []), "m": route.get("m")}
        c.update(status=status, t_status=now, **({"eta_s": eta_s} if eta_s is not None else {}))
        inc["crew"] = c
        if bids is not None:
            inc["bids"] = [{"crew": b.get("crew"), "name": crews.get(b.get("crew"), {}).get("name", b.get("crew")),
                            "eta_s": b.get("eta_s"), "can": b.get("can")} for b in bids]
        site = net.substation["name"] if inc["kind"] == "substation" else net.line_name(inc["line"])
        text = {"assigned": f"{name} won the work order ({len(inc['bids'])} crews bid; it is {route.get('m', 0) / 1000:.1f} km away "
                            f"on real streets, ETA {self._mins(eta_s)})",
                "en_route": f"{name} is driving to {site}",
                "on_site": f"{name} is on site at {site}",
                "repaired": f"{name} reports {site} repaired"}[status]
        inc["steps"].append({"t": now, "step": f"crew {status}", "text": text, "kind": SIM})
        if status == "repaired":
            inc["repaired_at"] = now
        self.tl.log("response", msg=text, incident=inc["id"], crew=crew, status=status, eta_s=eta_s)
        return self.tick(now)

    def _mins(self, eta_s: float | None) -> str:
        if eta_s is None:
            return "unknown"
        return f"{eta_s / 60:.0f} min"

    def end(self, now: float | None = None, why: str = "cleared") -> None:
        if self.cap_id:
            self.replay.pending_withdraw.append(self.cap_id)
        if self.inc is not None:
            self.tl.log("response", msg=f"incident over: {why}", incident=self.inc["id"])
        self.inc, self.cap_id, self.last = None, None, None

    # ------------------------------------------------------------------ the response, recomputed every second
    def _serve(self, zones: list[float], capacity: float) -> set[int]:
        """Which zones a source can carry: the smallest first, so the most blocks stay lit. Deterministic."""
        on, used = set(), 0.0
        for z in sorted(range(len(zones)), key=lambda i: (zones[i], i)):
            if used + zones[z] <= capacity + 1e-9:
                on.add(z); used += zones[z]
        return on

    def tick(self, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        inc = self.inc
        if inc is None:
            return None
        net = self.network(); cfg = net.cfg
        age, kind = now - inc["t0"], inc["kind"]
        done = inc["repaired_at"] is not None or (kind not in CREWED + ("grid_emergency",) and age >= SURGE_S)
        if (done and now - (inc["repaired_at"] or inc["t0"] + SURGE_S) >= DONE_S) or age >= MAX_S:
            self.end(now, "restored" if done else "timed out")
            return None
        # the square under the incident: shares of its normal load
        R = cfg["rating_pct"] / 100
        ok = 1.0
        if not done and kind == "substation":
            ok = 0.0
        elif not done and kind == "line":
            ok = 1 - cfg["line_loss_pct"] / 100
        g = inc["grid"]
        if not done and kind == "plant" and g and g.get("needed_after"):
            ok = min(1.0, g["served_after"] / g["needed_after"]) / R     # the grid's real shortfall, shared by the square
        if kind == "grid_emergency":
            last = self.replay.last or {}
            if self.replay.event is None or "emergency" not in self.replay.caps:
                done = True
            elif last.get("forecast_mw") and last.get("demand_mw"):
                ok = min(1.0, last["demand_mw"] / last["forecast_mw"]) / R   # recorded: served / needed this hour
        sub = ok * R
        homes = sum(net.load)
        zmult = 1.0 if done else (1 + (inc["mult"] - 1) / homes if kind == "ev_surge" else inc["mult"])
        zones = [l * zmult for l in net.load]
        H = net.critical_load * (1.0 if done or kind == "ev_surge" else inc["mult"])
        steps, names = inc["steps"], {s["step"] for s in inc["steps"]}

        def say(step, text, tag=SIM):
            if step not in names:
                steps.append({"t": now, "step": step, "text": text, "kind": tag}); names.add(step)
                self.tl.log("response", msg=text, incident=inc["id"], step=step, tag=tag)
            else:
                next(s for s in steps if s["step"] == step)["text"] = text

        # Griddy's actions, in the order that fits the incident, each only while the square is still short
        order = (["isolate", "protect", "reroute", "shed"] if kind in CREWED else
                 ["shed", "protect"] if kind in GRID_SHORT else ["shed", "reroute", "protect"])
        backup, F, shed = False, 0.0, False
        ai_cut, ours = self._ai(now, False)
        flex = 0.0
        short = lambda: sum(zones) * (1 - flex / sum(zones)) + (0.0 if backup else H) > sub + F + 1e-9   # noqa: E731
        if not done and kind == "solar_backfeed":
            if age >= 0.5:
                say("curtail", f"curtailed rooftop solar export to the feeders' {cfg['solar_limit_pct']} % limit through the "
                               f"inverters ({SIM}): voltage back in range, no one loses power")
        elif not done:
            for n, step in enumerate(order):
                if age < 0.5 + n or (step != "isolate" and not short()):
                    break
                if step == "isolate":
                    say("isolate", f"opened {net.substation['name']}'s breakers: the fault is cut off so it cannot spread"
                        if kind == "substation" else
                        f"opened the breakers at both ends of {net.line_name(inc['line'])}: de-energized, so a live wire "
                        f"cannot start a fire; the substation runs on its other line")
                elif step == "protect" and net.backup:
                    backup = True
                    say("protect", f"islanded the hospitals ({net.critical_load:.0%} of the load) onto "
                                   f"{' and '.join(b['name'] for b in net.backup)}: they never go dark")
                elif step == "reroute":
                    F = cfg["second_feed"]["spare_pct"] / 100
                    say("reroute", f"closed the tie switch to {cfg['second_feed']['name']}: it picks up {F:.0%} of the load")
                elif step == "shed":
                    shed = True
                    ai_cut, ours = self._ai(now, True)
                    ev = cfg["flexible"]["ev_pct"] / 100 + (inc["mult"] - 1 if kind == "ev_surge" else 0.0)
                    flex = min(sum(zones), cfg["flexible"]["ai_pct"] / 100 * ai_cut + ev)
                    base = inc["baseline_w"]
                    mac = (f"this Mac {base:.1f} W to {ours:.1f} W, measured" if base and ours is not None else "this Mac: measuring")
                    say("shed", f"paused the AI work that can wait at the data centers ({mac}; owners asked before any "
                                f"deadline slips) and staggered home EV charging ({SIM}): {flex:.0%} of the load freed", "measured + simulated")
        # who is lit, with Griddy and without it (the substation alone: no islanding, no tie, nothing shed)
        scale = 1 - flex / sum(zones) if sum(zones) else 1.0
        with_ = self._serve([z * scale for z in zones], max(0.0, sub + F - (0.0 if backup else H)))
        alone = self._serve(zones, max(0.0, sub - H))
        state = ["on" if z in alone else "griddy" if z in with_ else "off" for z in range(len(zones))]
        lit = lambda s: sum(net.load[z] for z in s) / homes                   # noqa: E731
        # the work order for the crews
        if kind in CREWED and not done and age >= 4.5 and inc["order"] is None:
            site = (inc["site"]["x"], inc["site"]["z"])
            routes = {}
            for c in cfg["crews"]:
                r = net.roads.route(net.depot(c["depot"]), site)
                if r:
                    routes[c["id"]] = {"m": round(r[0]), "pts": r[1]}
            inc["order"] = {"id": f"wo-{inc['id']}", "kind": kind,
                            "site": net.substation["name"] if kind == "substation" else net.line_name(inc["line"]),
                            "x": site[0], "z": site[1], "routes": routes, "speed_mps": cfg["speed_mps"],
                            "repair_s": cfg["repair_s"][kind], "travel_scale": cfg["travel_scale"], "repair_scale": cfg["repair_scale"],
                            "crews": cfg["crews"], "created": now}
            say("dispatch", f"sent a work order for {inc['order']['site']} to {len(cfg['crews'])} crew agents (Fetch.ai, {SIM} crews)")
        if inc["order"] and not inc["crew"] and now - inc["order"]["created"] >= NO_CREW_S:
            say("no crew", "no crew agent has answered the work order yet: start them with `make crews`", "status")
        if done:
            undo = ", ".join(x for x, s in (("opened the tie", "reroute"), ("hospitals back on the grid", "protect"),
                                             ("AI work resumes", "shed")) if s in names)
            say("restore", f"closed the breakers at {inc['order']['site'] if inc['order'] else net.substation['name']}"
                           f"{', ' + undo if undo else ''}: everything lit" if kind in CREWED else
                           "the surge is over: EV charging and AI work resume, everything lit")
            if self.cap_id:
                self.replay.pending_withdraw.append(self.cap_id); self.cap_id = None
        steps.sort(key=lambda s: s["t"])
        o = inc["order"]
        out = {"t": now, "id": inc["id"], "kind": kind, "what": inc["what"], "trigger": inc["trigger"], "age_s": age,
               "city": net.city_id, "site": inc["site"], "line": inc["line"] if kind == "line" else None,
               "line_pts": net.lines[inc["line"]]["p"] if kind == "line" and not done else None,
               "substation": {"name": net.substation["name"], "x": net.substation["x"], "z": net.substation["z"], "ok": ok},
               "zones": state, "hospitals": "central plants" if backup else "grid" if not short() or done else "own generators",
               "lit_with": lit(with_), "lit_without": lit(alone), "short": short() and not done,
               "flex": {"share": flex, "ai_cut_pct": 100 * ai_cut, "ours_w": ours, "baseline_w": inc["baseline_w"], "shed": shed},
               "steps": steps, "order": {k: o[k] for k in ("id", "site", "x", "z", "travel_scale", "repair_scale", "routes")} if o else None,
               "crew": inc["crew"], "bids": inc["bids"], "done": done,
               "real": "map, substation, plants, 138 kV lines, hospitals and streets: OpenStreetMap; this Mac's watts: measured",
               "simulated": "the fault, feeders, switches, ratings, EV charging, rooftop solar, crews and depots (config/networks.yaml)"}
        self.last = out
        return out

    def _ai(self, now: float, wanted: bool) -> tuple[float, float | None]:
        """This Mac's cut, measured, credited up to the share asked; asks the real dispatcher for it once."""
        inc = self.inc
        xs = [w for t, w in self.ex.power if t > now - 10]
        ours = sum(xs) / len(xs) if xs else None
        base = inc["baseline_w"]
        asked = float(self.cfg.get("emergency_cut_pct", 40))
        if wanted and self.cap_id is None and not getattr(self.whatif, "cap_id", None) and not self.replay.caps and base:
            ev = CapEvent(source="whatif", start=datetime.fromtimestamp(now).astimezone(), duration_s=int(MAX_S),
                          target_w=base * (1 - asked / 100), target_pct=asked, reason=f"emergency response: {inc['what']}",
                          raw="response/engine.py")
            self.cap_id = ev.id
            self.replay.pending_caps.append(ev)
        if not wanted or not base or ours is None:
            return 0.0, ours
        return max(0.0, min(1 - ours / base, asked / 100)), ours
