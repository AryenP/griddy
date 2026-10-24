"""Executes the current slot of the schedule on this Mac (SPEC §6) and decides when to re-solve.

Once a second: find the slot that contains now, turn its assignments into a SlotPlan, apply it
through the knobs (idempotent), log the plan whenever it changes, and log each job's status.
Re-solve on: a new grid signal, a policy change, a CapEvent, a job change (e.g. new deadline),
a job finishing, the schedule's horizon running out, chat traffic moving away from what the plan
assumed, or measured watts drifting from the plan. The LLM has no path into this module.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from datetime import datetime

from core.timeline import Timeline
from core.types import (Calibration, CapEvent, GridSignal, Job, PlanAction, Policy, PowerReading,
                        Schedule, SlotPlan)
from dispatcher.model import chat_w
from dispatcher.solve import load_jobs, solve

from .baseline import baseline_plan, pause_all_plan
from .knobs import Knobs

log = logging.getLogger("controller.execute")
JOBS = ("chat", "train", "batch")


class Executor:
    def __init__(self, tl: Timeline, knobs: Knobs, cal: Calibration, policy: Policy,
                 dispatcher_enabled: bool = True, baseline_window_s: int = 60, baseline_mode: str = "baseline"):
        self.tl, self.knobs, self.cal, self.policy = tl, knobs, cal, policy
        self.dispatcher_enabled = dispatcher_enabled
        self.baseline_mode = baseline_mode       # which naive policy runs when the dispatcher is off
        self.signal: GridSignal | None = None
        self.schedule: Schedule | None = None
        self.plan: SlotPlan | None = None
        self.events: list[CapEvent] = []
        self.job_changes: dict[str, dict] = {}
        self.hard_deadlines: set[str] = set()    # owner refused a slip: the deadline may not bend
        self.cap_overrides: set[frozenset[str]] = set()   # operator approved going over these caps
        self.cap_held: set[frozenset[str]] = set()        # operator refused going over these: chat may degrade
        self.needs_approval: list[str] = []      # approval request ids the current plan is waiting on
        self.schedule_listeners: list = []       # async callbacks(schedule), e.g. the agent bridge
        self.finished: set[str] = set()
        self.power: deque[tuple[float, float]] = deque(maxlen=3600)
        self.baseline_window_s = baseline_window_s
        self._lock = asyncio.Lock()
        self._plan_key = None
        self._last_latency_log = 0.0
        self._last_solve_t = 0.0
        self._plan_t = 0.0                       # when the plan in force last changed
        self.fleet = None                        # fleet.hub.Fleet when laptops may join (set by the runtime)
        self.background_w = 0.0                  # measured load outside the plan, as passed to the last solve
        self.chat_streams: deque[tuple[float, int]] = deque(maxlen=600)   # (t, chat requests in service)

    # ------------------------------------------------------------------ inputs
    def on_power(self, r: PowerReading) -> None:
        self.power.append((r.t, r.combined_w))

    def baseline_w(self) -> float | None:
        """Measured mean combined power over the last baseline window (pre-event baseline)."""
        cut = time.time() - self.baseline_window_s
        xs = [w for t, w in self.power if t >= cut]
        return sum(xs) / len(xs) if len(xs) >= self.baseline_window_s // 2 else None

    def solve_cal(self) -> Calibration:
        """The Mac's calibration, plus each online laptop's idle draw and job (fleet/hub.py)."""
        return self.fleet.calibration(self.cal) if self.fleet else self.cal

    def jobs(self) -> list[Job]:
        out = []
        for j in load_jobs(self.cal) + (self.fleet.jobs() if self.fleet else []):
            for k, v in self.job_changes.get(j.id, {}).items():
                setattr(j, k, v)
            if j.id in self.finished:
                j.state = "done"
                j.required_runtime_min = 0
            out.append(j)
        return out

    async def on_signal(self, sig: GridSignal) -> None:
        self.signal = sig
        await self.resolve("grid update")

    async def set_policy(self, **changes) -> Schedule | None:
        self.policy = self.policy.model_copy(update=changes)
        self.tl.log("policy", reason="operator change", changes=changes, **self.policy.model_dump(mode="json"))
        return await self.resolve("policy change")

    async def add_event(self, ev: CapEvent) -> Schedule | None:
        if ev.target_pct is not None and ev.target_w is None:
            base = self.baseline_w()
            if base is None:
                raise ValueError(f"no measured baseline yet (needs {self.baseline_window_s}s of power)")
            ev = ev.model_copy(update={"target_w": base * (1 - ev.target_pct / 100)})
            self.tl.log("note", msg=f"cap {ev.target_pct}% of measured baseline {base:.2f} W -> {ev.target_w:.2f} W",
                        baseline_w=base, baseline_window_s=self.baseline_window_s)
        self.events.append(ev)
        self.tl.log("event", **ev.model_dump(mode="json"))
        return await self.resolve("cap event")

    async def remove_event(self, event_id: str, reason: str) -> Schedule | None:
        """Withdraw a cap before its end (e.g. the simulated neighbourhood's replay was stopped)."""
        if not any(e.id == event_id for e in self.events):
            return None
        self.events = [e for e in self.events if e.id != event_id]
        self.tl.log("note", msg=f"cap {event_id} withdrawn: {reason}", cap_withdrawn=event_id)
        return await self.resolve("cap withdrawn")

    async def set_job(self, job_id: str, **changes) -> Schedule | None:
        self.job_changes.setdefault(job_id, {}).update(changes)
        self.tl.log("policy", reason="job change", job=job_id,
                    changes={k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in changes.items()})
        return await self.resolve("job change")

    async def keep_deadline(self, job_id: str, reason: str) -> Schedule | None:
        """The owner refused to let this job's deadline slip; re-solve with it hard."""
        self.hard_deadlines.add(job_id)
        self.tl.log("policy", reason="deadline kept by owner", job=job_id, owner_reason=reason)
        return await self.resolve("deadline kept")

    def set_dispatcher(self, enabled: bool) -> None:
        self.dispatcher_enabled = enabled
        self.tl.log("policy", reason="dispatcher toggle", dispatcher_enabled=enabled)
        self.tick()

    # ------------------------------------------------------------------ solve
    @staticmethod
    def chat_busy() -> float | None:
        """Measured average busy chat streams over the last 60 s, from the proxy (None until it reports)."""
        v = Knobs.status("chat").get("busy_60s")
        return float(v) if v is not None else None

    def cap_key(self) -> frozenset[str]:
        """Identifies the caps in force now: the active CapEvents plus a policy cap, if any. An operator's
        approval to go over the cap applies to exactly this set and lapses when it changes."""
        ids = {e.id for e in self.active_events()}
        if self.policy.power_cap_w is not None:
            ids.add(f"policy:{self.policy.power_cap_w}")
        return frozenset(ids)

    async def approve_over_cap(self, who: str) -> Schedule | None:
        key = self.cap_key()
        self.cap_overrides.add(key)
        self.tl.log("policy", reason="operator approved going over the cap", who=who, caps=sorted(key))
        return await self.resolve("over-cap approved")

    async def hold_cap(self, who: str, reason: str) -> Schedule | None:
        """The operator refused going over the cap: hold it with everything they control, which includes
        degrading chat (policy approvals.chat_degrade). Lapses when the caps in force change."""
        key = self.cap_key()
        self.cap_held.add(key)
        self.tl.log("policy", reason="operator refused going over the cap: chat may be degraded to hold it",
                    who=who, why=reason, caps=sorted(key))
        return await self.resolve("over-cap refused")

    def cap_in_force(self) -> bool:
        now = time.time()
        return self.policy.power_cap_w is not None or any(
            e.start.timestamp() <= now < e.start.timestamp() + e.duration_s for e in self.events)

    def active_events(self) -> list[CapEvent]:
        now = time.time()
        return [e for e in self.events if e.start.timestamp() + e.duration_s > now]

    async def resolve(self, reason: str) -> Schedule | None:
        if self.signal is None:
            return None
        async with self._lock:
            sig, jobs, events = self.signal, self.jobs(), self.active_events()
            sched = await asyncio.to_thread(solve, sig, jobs, self.policy, self.solve_cal(), events, self.baseline_w(),
                                            self.chat_busy(), frozenset(self.hard_deadlines),
                                            self.cap_key() in self.cap_overrides, self.background_w,
                                            self.cap_key() in self.cap_held)
            self.schedule = sched
            self._last_solve_t = time.time()
            self.tl.log("schedule", reason=reason, **sched.model_dump(mode="json"))
            for sf in sched.shortfalls:
                d = sf.model_dump(mode="json")
                self.tl.log("shortfall", schedule_id=sched.id, shortfall_kind=d.pop("kind"), **d)
        for cb in list(self.schedule_listeners):
            try:
                await cb(sched)
            except Exception as e:      # a listener (e.g. the agent) failing never stops execution
                log.exception("schedule listener failed")
                self.tl.log("note", level="error", msg=f"schedule listener failed: {e!r}"[:300])
        self.tick()
        return sched

    # ------------------------------------------------------------------ execute
    def slot_index(self) -> int | None:
        if not self.schedule:
            return None
        i = math.floor((time.time() - self.schedule.slots[0].timestamp()) / (self.schedule.slot_minutes * 60))
        return i if 0 <= i < len(self.schedule.slots) else None

    def current_plan(self) -> SlotPlan | None:
        jobs = self.jobs()
        if not self.dispatcher_enabled:
            if self.baseline_mode == "pause_all":
                return pause_all_plan(jobs, self.solve_cal(), self.cap_in_force())
            return baseline_plan(jobs, self.solve_cal())
        i = self.slot_index()
        if i is None:
            return None
        s = self.schedule
        actions = []
        for j in jobs:
            if j.id not in s.assignments:            # a laptop joined after this schedule: waits for the re-solve
                actions.append(PlanAction(job=j.id, state="pause"))
                continue
            a = s.assignments[j.id][i]
            if j.kind == "interactive":
                actions.append(PlanAction(job=j.id, state="run", device="gpu", concurrency=a.concurrency))
            elif j.id in self.finished:
                actions.append(PlanAction(job=j.id, state="done"))
            else:
                actions.append(PlanAction(job=j.id, state="run" if a.run else "pause", device=a.device))
        stale = bool(self.signal and self.signal.stale) or s.on_stale_data
        return SlotPlan(mode="dispatcher", schedule_id=s.id, slot_index=i, slot_start=s.slots[i], actions=actions,
                        planned_w=s.planned_w[i], cap_w=s.caps_w[i], on_last_known_data=stale,
                        needs_approval=list(self.needs_approval))

    def apply(self, plan: SlotPlan) -> None:
        sites = set(self.fleet.sites) if self.fleet else set()
        for site in sites - {a.job for a in plan.actions}:
            self.fleet.set_run(site, False)          # a laptop not in the plan never runs unplanned
        for a in plan.actions:
            if a.job in sites:
                self.fleet.set_run(a.job, a.state == "run")
                continue
            if a.state == "done":
                continue
            if a.job == "chat":
                self.knobs.set_concurrency("chat", a.concurrency or 0)
            elif a.state == "run":
                self.knobs.set_device(a.job, a.device)
                self.knobs.run(a.job)
            else:
                self.knobs.pause(a.job)

    def tick(self) -> SlotPlan | None:
        plan = self.current_plan()
        if plan is None:
            return None
        key = (plan.mode, plan.schedule_id, plan.slot_index, tuple(a.model_dump_json() for a in plan.actions))
        if key != self._plan_key:
            self._plan_key = key
            self._plan_t = time.time()
            self.plan = plan
            self.tl.log("plan", **plan.model_dump(mode="json"))
        self.apply(plan)
        return plan

    def _observe_jobs(self) -> list[str]:
        newly_done = []
        for j in JOBS:
            st = Knobs.status(j)
            if not st:
                continue
            self.tl.log("state", **{**st, "job": j})
            if j == "chat" and st.get("inflight") is not None:
                self.chat_streams.append((st.get("t", time.time()), int(st["inflight"])))
            if st.get("state") == "done" and j not in self.finished:
                self.finished.add(j)
                newly_done.append(j)
            if j == "chat" and time.time() - self._last_latency_log >= 5:
                self._last_latency_log = time.time()
                self.tl.log("latency", job="chat", p95_60s=st.get("p95_60s"), n_60s=st.get("n_60s"))
        return newly_done

    def drift_reason(self) -> str | None:
        """Why measured reality no longer matches the plan, if it doesn't (rate-limited by policy)."""
        r = self.policy.replan
        s, plan = self.schedule, self.plan
        if not (self.dispatcher_enabled and s and plan and r):
            return None
        now = time.time()
        if now - self._last_solve_t < r.get("min_interval_s", 60):
            return None
        busy = self.chat_busy()
        if busy is not None and s.chat_busy_streams is not None and \
                abs(busy - s.chat_busy_streams) > r.get("chat_busy_delta", 0.5):
            return f"chat traffic {s.chat_busy_streams:.2f} -> {busy:.2f} busy streams"
        # watts: only once the current slot has run a full window, so job start-up is not drift
        window = self.baseline_window_s
        lag = self.meter_lag_s()
        if plan.slot_start and plan.planned_w is not None and now - plan.slot_start.timestamp() >= window + 5 + lag \
                and now - self._last_solve_t >= window + lag:
            xs = [w for t, w in self.power if t >= now - window]
            if len(xs) >= window // 2:
                m = sum(xs) / len(xs)
                tol = max(r.get("watts_drift_pct", 20) / 100 * plan.planned_w, r.get("watts_drift_min_w", 2.0))
                if abs(m - plan.planned_w) > tol:
                    return f"measured {m:.2f} W vs planned {plan.planned_w:.2f} W over {window}s"
        return None

    def meter_lag_s(self) -> float:
        """Extra settling time while laptops are online: their battery readings follow load slowly."""
        return self.fleet.meter_lag_s if self.fleet and self.fleet.online() else 0.0

    def background_drift(self) -> float | None:
        """Under a cap, the measured load outside the plan when it has moved since the last solve.

        The meter reads the whole machine; the plan covers idle and Brownout's jobs only. Once the current
        plan has run a settled window, measured minus that calibrated plan is load nobody scheduled (the
        display, another app, a site's cooling). When it moves by more than `background_delta_w`, the solver
        must count it against the cap. Chat is priced from the requests in service over the same window, so a
        burst of replies is not outside load. Not while chat traffic is off the plan: that is the traffic
        re-solve's."""
        r, s, plan = self.policy.replan, self.schedule, self.plan
        if not (self.dispatcher_enabled and s and plan and r and plan.mode == "dispatcher") or plan.cap_w is None \
                or plan.planned_w is None:
            return None
        window = r.get("background_window_s", 20)
        now = time.time()
        if now - max(self._plan_t, self._last_solve_t) < window + r.get("settle_s", 5) + self.meter_lag_s():
            return None
        busy = self.chat_busy()
        if busy is not None and s.chat_busy_streams is not None and \
                abs(busy - s.chat_busy_streams) > r.get("chat_busy_delta", 0.5):
            return None
        xs = [w for t, w in self.power if t > now - window]
        if len(xs) < window // 2:
            return None
        expected = plan.planned_w - s.background_w
        chat = self._chat_w_measured(now - window)
        if chat is not None:      # chat is not outside load: price what it served in this window, not the plan's guess
            expected += chat[1] - chat[0]
        bg = max(0.0, sum(xs) / len(xs) - expected)
        return bg if abs(bg - s.background_w) > r.get("background_delta_w", 0.5) else None

    def _chat_w_measured(self, since: float) -> tuple[float, float] | None:
        """(planned, measured) chat watts for the window from `since`: what the plan priced chat at, and the
        calibrated curve over the requests the proxy actually had in service at each sample. A judge's reply
        streams for a few seconds at most of the GPU's power (evidence-chat, Sat 09:49), far from the 60-s mean."""
        job = next((j for j in self.jobs() if j.kind == "interactive"), None)
        a = next((x for x in self.plan.actions if job and x.job == job.id), None) if self.plan else None
        ns = [n for t, n in self.chat_streams if t > since]
        if job is None or a is None or len(ns) < 3:
            return None
        cal, conc = self.solve_cal(), a.concurrency or 0
        busy = self.schedule.chat_busy_streams
        planned = chat_w(job, cal, min(conc, conc if busy is None else busy))
        return planned, sum(chat_w(job, cal, min(n, conc)) for n in ns) / len(ns)

    def idle_drift(self) -> float | None:
        """A lower idle floor, measured in place, when the plan leaves only idle drawing power.

        Calibration measures idle once; if anything else was busy then, every plan is priced too high and
        jobs that fit the cap get paused (evidence3 re-run, Sat 04:09: calibrated idle 2.22 W, measured
        0.35-0.45 W). When every deferrable job is paused or done and chat is planned and measured at no
        traffic, the settled measured mean is idle plus outside load, so it bounds idle from above. It only
        ever lowers the floor: load above the plan is the background estimate's job."""
        r, s, plan = self.policy.replan, self.schedule, self.plan
        if not (self.dispatcher_enabled and s and plan and r and plan.mode == "dispatcher"):
            return None
        if self.fleet and self.fleet.online():
            return None                              # the measured total includes laptops: not the Mac's idle
        jobs = {j.id: j for j in self.jobs()}
        if any(a.state == "run" and jobs.get(a.job) is not None and jobs[a.job].kind != "interactive" for a in plan.actions):
            return None
        quiet = r.get("idle_busy_max", 0.05)
        busy = self.chat_busy()
        if s.chat_busy_streams is None or s.chat_busy_streams > quiet or busy is None or busy > quiet:
            return None
        window = r.get("background_window_s", 20)
        now = time.time()
        if now - max(self._plan_t, self._last_solve_t) < window + r.get("settle_s", 5) + self.meter_lag_s():
            return None
        xs = [w for t, w in self.power if t > now - window]
        if len(xs) < window // 2:
            return None
        m = sum(xs) / len(xs)
        return m if m < self.cal.idle_w - r.get("background_delta_w", 0.5) else None

    async def run(self, period_s: float = 1.0) -> None:
        while True:
            try:
                for j in self._observe_jobs():
                    await self.resolve(f"{j} finished")
                if self.dispatcher_enabled and self.schedule and self.slot_index() is None:
                    await self.resolve("horizon exhausted")
                if self.fleet:
                    change = self.fleet.membership_changed()
                    if change:
                        during = self.cap_in_force()
                        self.tl.log("note", msg=f"re-solve: fleet {change}" + (" during a cap: a laptop that left is no longer in "
                                    "the measured total" if during and "left" in change else ""), trigger="fleet",
                                    online=self.fleet.online(), during_cap=during)
                        await self.resolve(f"fleet: {change}")
                idle = self.idle_drift()
                if idle is not None:
                    old = self.cal.idle_w
                    self.cal = self.cal.model_copy(update={"idle_w": idle})
                    why = f"idle floor {old:.2f} -> {idle:.2f} W, measured with only idle planned"
                    self.tl.log("note", msg=f"re-solve: {why}", trigger="idle", idle_w=idle, calibrated_idle_w=old)
                    await self.resolve(f"drift: {why}")
                bg = self.background_drift()
                if bg is not None:
                    old, self.background_w = self.background_w, bg
                    why = f"load outside the plan {old:.2f} -> {bg:.2f} W under the cap"
                    self.tl.log("note", msg=f"re-solve: {why}", trigger="background", background_w=bg)
                    await self.resolve(f"drift: {why}")
                why = self.drift_reason()
                if why:
                    self.tl.log("note", msg=f"re-solve: {why}", trigger="drift")
                    await self.resolve(f"drift: {why}")
                self.tick()
            except Exception as e:      # keep executing; the failure is on the timeline
                log.exception("executor tick failed")
                self.tl.log("note", level="error", msg=f"executor tick failed: {e!r}"[:300])
            await asyncio.sleep(period_s)
