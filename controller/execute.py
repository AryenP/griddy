"""Executes the current slot of the schedule on this Mac (SPEC §6) and decides when to re-solve.

Once a second: find the slot that contains now, turn its assignments into a SlotPlan, apply it
through the knobs (idempotent), log the plan whenever it changes, and log each job's status.
Re-solve on: a new grid signal, a policy change, a CapEvent, a job change (e.g. new deadline),
a job finishing, or the schedule's horizon running out. The LLM has no path into this module.
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
from dispatcher.solve import load_jobs, solve

from .baseline import baseline_plan
from .knobs import Knobs

log = logging.getLogger("controller.execute")
JOBS = ("chat", "train", "batch")


class Executor:
    def __init__(self, tl: Timeline, knobs: Knobs, cal: Calibration, policy: Policy,
                 dispatcher_enabled: bool = True, baseline_window_s: int = 60):
        self.tl, self.knobs, self.cal, self.policy = tl, knobs, cal, policy
        self.dispatcher_enabled = dispatcher_enabled
        self.signal: GridSignal | None = None
        self.schedule: Schedule | None = None
        self.plan: SlotPlan | None = None
        self.events: list[CapEvent] = []
        self.job_changes: dict[str, dict] = {}
        self.finished: set[str] = set()
        self.power: deque[tuple[float, float]] = deque(maxlen=3600)
        self.baseline_window_s = baseline_window_s
        self._lock = asyncio.Lock()
        self._plan_key = None
        self._last_latency_log = 0.0

    # ------------------------------------------------------------------ inputs
    def on_power(self, r: PowerReading) -> None:
        self.power.append((r.t, r.combined_w))

    def baseline_w(self) -> float | None:
        """Measured mean combined power over the last baseline window (pre-event baseline)."""
        cut = time.time() - self.baseline_window_s
        xs = [w for t, w in self.power if t >= cut]
        return sum(xs) / len(xs) if len(xs) >= self.baseline_window_s // 2 else None

    def jobs(self) -> list[Job]:
        out = []
        for j in load_jobs(self.cal):
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

    async def set_job(self, job_id: str, **changes) -> Schedule | None:
        self.job_changes.setdefault(job_id, {}).update(changes)
        self.tl.log("policy", reason="job change", job=job_id,
                    changes={k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in changes.items()})
        return await self.resolve("job change")

    def set_dispatcher(self, enabled: bool) -> None:
        self.dispatcher_enabled = enabled
        self.tl.log("policy", reason="dispatcher toggle", dispatcher_enabled=enabled)
        self.tick()

    # ------------------------------------------------------------------ solve
    def active_events(self) -> list[CapEvent]:
        now = time.time()
        return [e for e in self.events if e.start.timestamp() + e.duration_s > now]

    async def resolve(self, reason: str) -> Schedule | None:
        if self.signal is None:
            return None
        async with self._lock:
            sig, jobs, events = self.signal, self.jobs(), self.active_events()
            sched = await asyncio.to_thread(solve, sig, jobs, self.policy, self.cal, events, self.baseline_w())
            self.schedule = sched
            self.tl.log("schedule", reason=reason, **sched.model_dump(mode="json"))
            for sf in sched.shortfalls:
                self.tl.log("shortfall", schedule_id=sched.id, **sf.model_dump(mode="json"))
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
            return baseline_plan(jobs, self.cal)
        i = self.slot_index()
        if i is None:
            return None
        s = self.schedule
        actions = []
        for j in jobs:
            a = s.assignments[j.id][i]
            if j.kind == "interactive":
                actions.append(PlanAction(job=j.id, state="run", device="gpu", concurrency=a.concurrency))
            elif j.id in self.finished:
                actions.append(PlanAction(job=j.id, state="done"))
            else:
                actions.append(PlanAction(job=j.id, state="run" if a.run else "pause", device=a.device))
        stale = bool(self.signal and self.signal.stale) or s.on_stale_data
        return SlotPlan(mode="dispatcher", schedule_id=s.id, slot_index=i, slot_start=s.slots[i], actions=actions,
                        planned_w=s.planned_w[i], cap_w=s.caps_w[i], on_last_known_data=stale)

    def apply(self, plan: SlotPlan) -> None:
        for a in plan.actions:
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
            if st.get("state") == "done" and j not in self.finished:
                self.finished.add(j)
                newly_done.append(j)
            if j == "chat" and time.time() - self._last_latency_log >= 5:
                self._last_latency_log = time.time()
                self.tl.log("latency", job="chat", p95_60s=st.get("p95_60s"), n_60s=st.get("n_60s"))
        return newly_done

    async def run(self, period_s: float = 1.0) -> None:
        while True:
            try:
                for j in self._observe_jobs():
                    await self.resolve(f"{j} finished")
                if self.dispatcher_enabled and self.schedule and self.slot_index() is None:
                    await self.resolve("horizon exhausted")
                self.tick()
            except Exception as e:      # keep executing; the failure is on the timeline
                log.exception("executor tick failed")
                self.tl.log("note", level="error", msg=f"executor tick failed: {e!r}"[:300])
            await asyncio.sleep(period_s)
