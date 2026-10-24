"""Dispatcher OFF (SPEC §6). Two naive policies, each run by the same executor with the same logging so
runs compare with the dispatcher's:
- `baseline` (ignore the call): run every unfinished job now on the GPU, chat at full concurrency; ignore
  prices, carbon and caps.
- `pause_all` (the blunt demand-response answer): the same, except that while a cap is in force every
  deferrable job is paused and chat keeps running; no rescheduling, no device change, no approvals."""
from __future__ import annotations

from core.types import Calibration, Job, PlanAction, SlotPlan


def baseline_plan(jobs: list[Job], cal: Calibration) -> SlotPlan:
    actions = []
    for j in jobs:
        if j.kind == "interactive":
            actions.append(PlanAction(job=j.id, state="run", device="gpu", concurrency=j.max_concurrency))
        elif j.state == "done":
            actions.append(PlanAction(job=j.id, state="done"))
        else:
            measured = cal.jobs.get(j.id, {})
            dev = "gpu" if "gpu" in measured or j.device == "gpu" else "cpu"
            actions.append(PlanAction(job=j.id, state="run", device=dev))
    return SlotPlan(mode="baseline", actions=actions)


def pause_all_plan(jobs: list[Job], cal: Calibration, cap_in_force: bool) -> SlotPlan:
    plan = baseline_plan(jobs, cal)
    if cap_in_force:
        plan.actions = [a if a.job == "chat" or a.state == "done" else PlanAction(job=a.job, state="pause")
                        for a in plan.actions]
    plan.mode = "pause_all"
    return plan
