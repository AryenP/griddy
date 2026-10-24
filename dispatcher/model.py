"""CP-SAT model over the horizon (SPEC §5). Pure: inputs in, model + variables out.

Integer units inside the model:
  power  milliwatts (this Mac's job deltas are a few watts; whole watts would round them away)
  work   milli-slots of GPU-speed running: one slot on the GPU = 1000, one on the CPU =
         1000 x measured cpu_rate / gpu_rate
Objective per slot = W x slot_h x (w_cost x price/mean_price + w_carbon x carbon/mean_carbon),
plus a chat-degrade penalty, plus a tie-breaker (slot index) far below any real price difference. Normalising by the horizon mean makes cost and carbon comparable
without inventing an exchange rate between dollars and grams.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from core.types import Calibration, Job, Policy

SCALE = 1000
OBJ_SCALE = 1_000_000   # objective resolution; leaves room for the tie-breaker below


@dataclass
class Inputs:
    jobs: list[Job]
    cal: Calibration
    policy: Policy
    prices: list[float]              # $/MWh per slot
    carbons: list[float]             # gCO2/kWh per slot
    cap_w: list[float | None]        # machine watts cap per slot (policy cap or active CapEvent)
    deadline_slot: dict[str, int]    # job id -> number of slots ending on or before its deadline
    remaining_work: dict[str, int]   # job id -> milli-slots of GPU-speed work still to do
    chat_busy: float | None = None   # measured avg busy chat streams; None = plan for full concurrency


@dataclass
class Relax:
    """Which hard constraints may bend, to find the minimal relaxation when infeasible.
    `fixed`: jobs whose deadline may not bend even when deadlines are relaxed (the owner refused)."""
    deadlines: bool = False
    cap: bool = False
    fixed: frozenset[str] = frozenset()

    def may_slip(self, job_id: str) -> bool:
        return self.deadlines and job_id not in self.fixed


@dataclass
class Built:
    model: cp_model.CpModel
    x: dict[tuple[str, int, str], cp_model.IntVar] = field(default_factory=dict)
    conc: dict[int, cp_model.IntVar] = field(default_factory=dict)   # chat concurrency per slot
    miss: dict[str, cp_model.IntVar] = field(default_factory=dict)   # work not done by deadline
    over_mw: dict[int, cp_model.IntVar] = field(default_factory=dict)  # mW over cap per slot
    power_mw: list = field(default_factory=list)                      # per-slot linear expr
    chat_id: str | None = None


def objective_weights(policy: Policy) -> tuple[float, float]:
    if policy.objective == "cost":
        return 1.0, 0.0
    if policy.objective == "carbon":
        return 0.0, 1.0
    return policy.weights.get("cost", 0.5), policy.weights.get("carbon", 0.5)


def devices_for(job: Job, cal: Calibration) -> list[str]:
    allowed = ["gpu", "cpu"] if job.device == "either" else [job.device]
    return [d for d in allowed if d in cal.jobs.get(job.id, {})]


def speed(job: Job, cal: Calibration, dev: str) -> int:
    """Work per slot in milli-slots; the GPU is the reference speed when it was measured."""
    m = cal.jobs[job.id]
    ref = m.get("gpu")
    if dev == "gpu" or ref is None or not (m[dev].rate and ref.rate):
        return SCALE
    return max(1, round(SCALE * m[dev].rate / ref.rate))


def chat_w_per_conc(job: Job, cal: Calibration) -> float:
    p = cal.jobs[job.id]["gpu"]
    return p.delta_w / max(1, p.concurrency or 1)


def build(inp: Inputs, relax: Relax = Relax()) -> Built:
    m = cp_model.CpModel()
    S = len(inp.prices)
    slot_h = inp.policy.slot_minutes / 60
    pmean = (sum(max(p, 0.0) for p in inp.prices) / S) or 1.0
    cmean = (sum(inp.carbons) / S) or 1.0
    wc, wg = objective_weights(inp.policy)
    # integer objective cost of running 1 W for slot s
    unit = [OBJ_SCALE * slot_h * (wc * max(p, 0.0) / pmean + wg * c / cmean)
            for p, c in zip(inp.prices, inp.carbons)]

    b = Built(model=m)
    obj = []
    power = [[] for _ in range(S)]

    for job in inp.jobs:
        devs = devices_for(job, inp.cal)
        if not devs:
            raise ValueError(f"job {job.id} has no calibrated device; run `make calibrate`")

        if job.kind == "interactive":
            b.chat_id = job.id
            per_w = chat_w_per_conc(job, inp.cal)
            lo = max(job.min_concurrency, 1 if job.id in inp.policy.never_pause else 0)
            degrade = inp.policy.weights.get("chat_degrade", 10.0)
            penalty = round(degrade * max(unit) * max(per_w, 1.0))
            for s in range(S):
                c = m.NewIntVar(lo, job.max_concurrency, f"conc_{job.id}_{s}")
                b.conc[s] = c
                if inp.chat_busy is None:
                    streams = c                      # worst case: every slot of concurrency busy
                    per_unit = per_w                 # W per stream
                else:
                    # chat draws power for the streams actually in service: min(concurrency, measured
                    # traffic). Centi-streams keep the integer model precise for fractional traffic.
                    busy = round(min(inp.chat_busy, job.max_concurrency) * 100)
                    streams = m.NewIntVar(0, job.max_concurrency * 100, f"busy_{job.id}_{s}")
                    m.AddMinEquality(streams, [c * 100, busy])
                    per_unit = per_w / 100
                power[s].append(round(per_unit * 1000) * streams)
                obj.append(round(per_unit * unit[s]) * streams)
                obj.append(penalty * (job.max_concurrency - c))  # below max costs more than it saves
            continue

        last = min(inp.deadline_slot[job.id], S)
        for s in range(S):
            run = []
            for d in devs:
                v = m.NewBoolVar(f"x_{job.id}_{s}_{d}")
                b.x[(job.id, s, d)] = v
                run.append(v)
                w = inp.cal.jobs[job.id][d].delta_w
                power[s].append(round(w * 1000) * v)
                # + s: among equally priced slots prefer the earlier one (finish sooner), so the
                # optimum is unique and the schedule is reproducible from its inputs
                obj.append((round(w * unit[s]) + s) * v)
            m.Add(sum(run) <= 1)
            if job.id in inp.policy.never_pause:
                m.Add(sum(run) == 1)
            if s >= last and not relax.may_slip(job.id):
                m.Add(sum(run) == 0)

        need = inp.remaining_work[job.id]
        on_time = sum(speed(job, inp.cal, d) * b.x[(job.id, s, d)] for s in range(last) for d in devs)
        if relax.may_slip(job.id):
            miss = m.NewIntVar(0, need, f"miss_{job.id}")
            b.miss[job.id] = miss
            m.Add(on_time + miss >= need)
            late = sum(speed(job, inp.cal, d) * b.x[(job.id, s, d)] for s in range(last, S) for d in devs)
            m.Add(late >= miss)          # the slipped work still gets done, after the deadline
        else:
            m.Add(on_time >= need)

        if not job.interruptible:
            starts = []
            for s in range(S):
                r = sum(b.x[(job.id, s, d)] for d in devs)
                prev = sum(b.x[(job.id, s - 1, d)] for d in devs) if s else 0
                st = m.NewBoolVar(f"start_{job.id}_{s}")
                m.Add(st >= r - prev)
                starts.append(st)
            m.Add(sum(starts) <= 1)

    idle_mw = round(inp.cal.idle_w * 1000)
    for s in range(S):
        expr = sum(power[s]) + idle_mw
        b.power_mw.append(expr)
        cap = inp.cap_w[s]
        if cap is None:
            continue
        cap_mw = int(cap * 1000)
        if relax.cap:
            o = m.NewIntVar(0, 1_000_000, f"over_{s}")
            b.over_mw[s] = o
            m.Add(expr <= cap_mw + o)
        else:
            m.Add(expr <= cap_mw)

    if relax.deadlines or relax.cap:
        # Minimal relaxation first (milli-slots of slip, mW over cap), then the usual objective.
        big = int(sum(unit) * 1000) + 1
        obj.append(big * (sum(b.miss.values()) + sum(b.over_mw.values())))
    m.Minimize(sum(obj))
    return b
