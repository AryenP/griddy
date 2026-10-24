"""Dispatcher OFF (SPEC §6): run every unfinished job now, on the GPU where measured, chat at full
concurrency; ignore prices, carbon and caps. Same executor, same logging, so runs compare."""
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
