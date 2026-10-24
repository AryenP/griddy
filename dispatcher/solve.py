"""Solve the 24-h schedule (SPEC §5): CP-SAT with a time limit; if infeasible, the minimal
relaxation as Shortfalls; greedy priority schedule only if CP-SAT hits its limit with nothing.

    uv run python -m dispatcher.solve --print           # live grid + measured calibration
"""
from __future__ import annotations

import argparse
import asyncio
import math
import time
from datetime import datetime
from pathlib import Path

from ortools.sat.python import cp_model

from core import config
from core.timeline import Timeline
from core.types import (Calibration, CapEvent, DeadlineMiss, GridSignal, Job, Policy, Schedule,
                        Shortfall, SlotAssignment)

from .model import SCALE, Built, Inputs, Relax, build, devices_for, speed
from .schedule import explain, render


# ---------------------------------------------------------------- inputs from config + state
def load_policy(overrides: dict | None = None) -> Policy:
    return Policy(**{**config.policy, **(overrides or {})})


def load_jobs(cal: Calibration | None = None) -> list[Job]:
    """Jobs from config, with runtime and energy DERIVED from measured calibration and the
    workloads' own progress files: remaining work / measured GPU rate. Nothing typed in."""
    from workloads import batch, train
    work = {"train": lambda j: (train.progress()["step"], j.target_steps),
            "batch": lambda j: (batch.progress()["items_done"], batch.progress()["total"])}
    out = []
    for raw in config.jobs["jobs"]:
        job = Job(**raw)
        m = (cal.jobs.get(job.id) if cal else None) or {}
        ref = m.get("gpu") or next(iter(m.values()), None)
        if ref:
            job.measured_w = ref.delta_w
        if job.id in work and ref and ref.rate:
            done, total = work[job.id](job)
            job.progress = {"done": done, "total": total, "fraction": done / total if total else 1.0}
            job.required_runtime_min = math.ceil(max(0, total - done) / ref.rate / 60)
            job.energy_kwh_est = ref.delta_w * job.required_runtime_min / 60 / 1000
        out.append(job)
    return out


def load_calibration(path: str | Path | None = None) -> Calibration:
    p = Path(path or config.settings.calibration_path)
    if not p.exists():
        raise SystemExit(f"no calibration at {p}: run `make calibrate` (watts are measured, never typed)")
    return Calibration.model_validate_json(p.read_text())


def cap_per_slot(slots: list[datetime], slot_minutes: int, policy: Policy,
                 events: list[CapEvent], baseline_w: float | None) -> list[float | None]:
    caps: list[float | None] = [policy.power_cap_w] * len(slots)
    for ev in events:
        if ev.target_w is not None:
            target = ev.target_w
        elif ev.target_pct is not None and baseline_w:
            target = baseline_w * (1 - ev.target_pct / 100)
        else:
            continue
        end = ev.start.timestamp() + ev.duration_s
        for i, s in enumerate(slots):
            s0, s1 = s.timestamp(), s.timestamp() + slot_minutes * 60
            if s0 < end and s1 > ev.start.timestamp():      # slot overlaps the event window
                caps[i] = target if caps[i] is None else min(caps[i], target)
    return caps


def deadline_slots(jobs: list[Job], slots: list[datetime], slot_minutes: int) -> tuple[dict[str, int], list[str]]:
    """Slots that END on or before each deadline. A deadline past the horizon (or none) means
    'by the end of the horizon': conservative, and the rolling re-solve moves the horizon."""
    out, notes = {}, []
    horizon_end = slots[-1].timestamp() + slot_minutes * 60
    for j in jobs:
        if j.kind == "interactive":
            continue
        if j.deadline is None or j.deadline.timestamp() >= horizon_end:
            out[j.id] = len(slots)
            why = "has no deadline" if j.deadline is None else f"deadline {j.deadline:%a %H:%M} is past the horizon"
            notes.append(f"{j.id} {why}: planned to finish within this 24-h horizon")
        else:
            out[j.id] = sum(1 for s in slots if s.timestamp() + slot_minutes * 60 <= j.deadline.timestamp())
    return out, notes


def remaining(jobs: list[Job], slot_minutes: int) -> dict[str, int]:
    out = {}
    for j in jobs:
        if j.kind == "interactive":
            continue
        if j.required_runtime_min is None:
            raise SystemExit(f"{j.id}: no measured rate; run `make calibrate`")
        out[j.id] = math.ceil(SCALE * j.required_runtime_min / slot_minutes)
    return out


# ---------------------------------------------------------------- solving
def _run(b: Built, limit_s: float) -> tuple[cp_model.CpSolver, int]:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = limit_s
    solver.parameters.num_workers = 8
    solver.parameters.random_seed = 0          # deterministic and reproducible from inputs
    # CP-SAT's Ctrl-C catching, run from a worker thread, leaves SIGINT at the default action afterwards,
    # which killed the runtime without its shutdown (no checkpoint, orphaned workloads). The runtime owns SIGINT.
    solver.parameters.catch_sigint_signal = False
    return solver, solver.Solve(b.model)


def _extract(inp: Inputs, b: Built, solver: cp_model.CpSolver) -> tuple[dict[str, list[SlotAssignment]], list[float]]:
    S = len(inp.prices)
    out: dict[str, list[SlotAssignment]] = {}
    for job in inp.jobs:
        row = []
        for s in range(S):
            if job.kind == "interactive":
                c = int(solver.Value(b.conc[s]))
                row.append(SlotAssignment(run=c > 0, concurrency=c, device="gpu" if c else None))
                continue
            dev = next((d for d in devices_for(job, inp.cal) if solver.Value(b.x[(job.id, s, d)])), None)
            row.append(SlotAssignment(run=dev is not None, concurrency=1 if dev else 0, device=dev))
        out[job.id] = row
    watts = [solver.Value(e) / 1000 for e in b.power_mw]
    return out, watts


def greedy(inp: Inputs) -> tuple[dict[str, list[SlotAssignment]], list[float]]:
    """Fallback only when CP-SAT times out with no solution: chat at max (min under a cap), then
    each job in priority order takes its cheapest (slot, device) pairs that fit the cap."""
    from .model import chat_w_per_conc, objective_weights
    S = len(inp.prices)
    wc, wg = objective_weights(inp.policy)
    pmean = (sum(max(p, 0) for p in inp.prices) / S) or 1
    cmean = (sum(inp.carbons) / S) or 1
    unit = [wc * max(p, 0) / pmean + wg * c / cmean for p, c in zip(inp.prices, inp.carbons)]
    watts = [inp.cal.idle_w + max(0.0, inp.background_w)] * S
    out: dict[str, list[SlotAssignment]] = {}
    for job in sorted(inp.jobs, key=lambda j: j.priority):
        if job.kind == "interactive":
            per = chat_w_per_conc(job, inp.cal)
            row = []
            for s in range(S):
                c = job.max_concurrency
                while inp.cap_w[s] is not None and c > job.min_concurrency and watts[s] + per * c > inp.cap_w[s]:
                    c -= 1
                watts[s] += per * c
                row.append(SlotAssignment(run=True, concurrency=c, device="gpu"))
            out[job.id] = row
            continue
        row = [SlotAssignment(run=False) for _ in range(S)]
        need = inp.remaining_work[job.id]
        cands = sorted(((inp.cal.jobs[job.id][d].delta_w * unit[s] / speed(job, inp.cal, d), s, d)
                        for s in range(inp.deadline_slot[job.id]) for d in devices_for(job, inp.cal)))
        for _, s, d in cands:
            if need <= 0:
                break
            w = inp.cal.jobs[job.id][d].delta_w
            if row[s].run or (inp.cap_w[s] is not None and watts[s] + w > inp.cap_w[s]):
                continue
            row[s] = SlotAssignment(run=True, concurrency=1, device=d)
            watts[s] += w
            need -= speed(job, inp.cal, d)
        out[job.id] = row
    return out, watts


def _relaxation(inp: Inputs, relax: Relax, limit_s: float, slots: list[datetime], slot_minutes: int) -> list[Shortfall]:
    b = build(inp, relax)
    solver, st = _run(b, limit_s)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []
    out = []
    for jid, v in b.miss.items():
        miss = solver.Value(v)
        if miss:
            minutes = math.ceil(miss / SCALE * slot_minutes)
            out.append(Shortfall(kind="deadline", job_id=jid, amount=minutes,
                                 message=f"keeping the cap, {jid} needs {minutes} more min of GPU time after its deadline"))
    over = {s: solver.Value(v) / 1000 for s, v in b.over_mw.items() if solver.Value(v)}
    if over:
        worst = max(over.values())
        first = min(over)
        out.append(Shortfall(kind="cap", amount=round(worst, 2),
                             message=f"keeping every deadline, power exceeds the cap by up to {worst:.2f} W "
                                     f"in {len(over)} slot(s) from {slots[first]:%H:%M}"))
    return out


def solve(sig: GridSignal, jobs: list[Job], policy: Policy, cal: Calibration,
          events: list[CapEvent] | None = None, baseline_w: float | None = None,
          chat_busy: float | None = None, hard_deadlines: frozenset[str] = frozenset(),
          exceed_cap_approved: bool = False, background_w: float = 0.0) -> Schedule:
    """If the model is infeasible, two honest options go to the negotiator (shortfalls): slip deadlines
    under the cap, or exceed the cap (`hard_deadlines` = owners refused a slip). What RUNS meanwhile holds
    the utility's cap and lets deadlines slip, unless the operator approved going over the cap for these
    events (`exceed_cap_approved`); the cap bends without approval only if nothing at all fits under it.
    `background_w`: measured load outside the plan, which counts against the cap in every slot."""
    background_w = max(0.0, background_w)
    t0 = time.time()
    slots = [s for s, _ in sig.price_curve]
    prices = [p for _, p in sig.price_curve]
    carbons = [c for _, c in sig.carbon_curve] if sig.carbon_curve else [0.0] * len(slots)
    dl, notes = deadline_slots(jobs, slots, policy.slot_minutes)
    inp = Inputs(jobs=jobs, cal=cal, policy=policy, prices=prices, carbons=carbons,
                 cap_w=cap_per_slot(slots, policy.slot_minutes, policy, events or [], baseline_w),
                 deadline_slot=dl, remaining_work=remaining(jobs, policy.slot_minutes), chat_busy=chat_busy,
                 background_w=background_w)
    if background_w and any(c is not None for c in inp.cap_w):
        notes = notes + [f"measured load outside the plan: {background_w:.2f} W (meter minus the calibrated plan), "
                         f"counted against the cap"]

    b = build(inp)
    solver, st = _run(b, policy.solver_time_limit_s)
    shortfalls: list[Shortfall] = []
    relaxed = False
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assign, watts = _extract(inp, b, solver)
        status = solver.StatusName(st)
        obj = solver.ObjectiveValue()
    elif st == cp_model.INFEASIBLE:
        # Two honest options for the negotiator: slip deadlines under the cap, or exceed the cap.
        hard = frozenset(hard_deadlines)
        shortfalls = (_relaxation(inp, Relax(deadlines=True, fixed=hard), policy.solver_time_limit_s, slots, policy.slot_minutes)
                      + _relaxation(inp, Relax(cap=True), policy.solver_time_limit_s, slots, policy.slot_minutes))
        cap_mode = "over the cap: approved by the operator"
        rb, rs, rst = None, None, None
        if not exceed_cap_approved:                      # the safe default: hold the cap, deadlines slip
            rb = build(inp, Relax(deadlines=True))
            rs, rst = _run(rb, policy.solver_time_limit_s)
            cap_mode = "cap held; deadlines slip until an approval says otherwise"
        if rst not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            rb = build(inp, Relax(deadlines=True, cap=True, fixed=hard))
            rs, rst = _run(rb, policy.solver_time_limit_s)
            if not exceed_cap_approved:
                cap_mode = "over the cap without approval: nothing fits under it (minimum load exceeds the cap)"
        assign, watts = _extract(inp, rb, rs)
        status, obj, relaxed = "INFEASIBLE -> minimal relaxation", rs.ObjectiveValue(), True
        notes = notes + [f"running plan: {cap_mode}"]
    else:
        assign, watts = greedy(inp)
        status, obj = f"GREEDY (CP-SAT {solver.StatusName(st)} at {policy.solver_time_limit_s}s limit)", 0.0

    slot_h = policy.slot_minutes / 60
    cost = sum(w * slot_h / 1e6 * max(p, 0) for w, p in zip(watts, prices))
    co2 = sum(w * slot_h / 1000 * c for w, c in zip(watts, carbons))
    misses = []
    for j in jobs:
        if j.kind == "interactive" or j.deadline is None or dl[j.id] >= len(slots):
            continue
        late = [i for i, a in enumerate(assign[j.id]) if a.run and i >= dl[j.id]]
        if late:
            fin = slots[late[-1]].timestamp() + policy.slot_minutes * 60
            misses.append(DeadlineMiss(job_id=j.id, deadline=j.deadline,
                                       finishes_at=datetime.fromtimestamp(fin, tz=slots[0].tzinfo),
                                       slip_min=round((fin - j.deadline.timestamp()) / 60)))

    sched = Schedule(slot_minutes=policy.slot_minutes, slots=slots, assignments=assign,
                     objective_value=obj, cost_usd=cost, co2_g=co2, deadline_misses=misses,
                     shortfalls=shortfalls, solver_status=status, solve_wall_s=time.time() - t0,
                     relaxed=relaxed, on_stale_data=sig.stale, planned_w=watts, caps_w=inp.cap_w,
                     chat_busy_streams=chat_busy, background_w=background_w)
    sched.explanations = notes + explain(sched, sig, jobs, dl)
    return sched


# ---------------------------------------------------------------- CLI
async def _live_signal(tl: Timeline) -> GridSignal:
    from grid.watcher import GridWatcher
    return await GridWatcher(config.settings.iso, config.settings.location, tl).refresh_all()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="print the schedule table")
    ap.add_argument("--objective", choices=["cost", "carbon", "balanced"])
    ap.add_argument("--cap-w", type=float, help="machine power cap in W for the whole horizon")
    a = ap.parse_args()
    cal = load_calibration()
    over = {k: v for k, v in {"objective": a.objective, "power_cap_w": a.cap_w}.items() if v is not None}
    policy, jobs = load_policy(over), load_jobs(cal)
    tl = Timeline(run_id=time.strftime("%Y%m%d-%H%M%S") + "-solve")
    sig = asyncio.run(_live_signal(tl))
    tl.log("policy", **policy.model_dump(mode="json"))
    sched = solve(sig, jobs, policy, cal)
    tl.log("schedule", **sched.model_dump(mode="json"))
    tl.close()
    if a.print:
        print(render(sched, sig, jobs, cal))
    print(f"\ntimeline: {tl.path}")


if __name__ == "__main__":
    main()
