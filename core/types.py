"""Shared data types. Everything that crosses a module boundary is one of these."""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

WorkloadKind = Literal["interactive", "deferrable", "droppable"]
WorkloadState = Literal["running", "throttled", "paused", "deferred", "killed"]


def now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class Workload(BaseModel):
    id: str
    kind: WorkloadKind
    priority: int = Field(ge=1, description="1 = most important")
    owner: str
    sla: dict[str, Any] = Field(default_factory=dict)
    interruptible: bool = True
    state: WorkloadState = "running"
    est_watts: float = 0.0
    progress: dict[str, Any] = Field(default_factory=dict)


class PowerSample(BaseModel):
    t: float = Field(default_factory=now)
    nvml_w: float | None = None
    wall_w: float | None = None
    wall_age_s: float | None = None
    fused_w: float | None = None
    source: str = "sim"


class CapRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("req"))
    source: Literal["openadr", "email", "voice", "ui"]
    target_w: float | None = None
    target_pct: float | None = None  # reduction vs baseline, 0-100
    start: datetime
    duration_s: int
    raw: str
    constraints: list[str] = Field(default_factory=list)
    requester: str = "utility"


class Action(BaseModel):
    rung: int
    name: str
    params: dict[str, Any] = Field(default_factory=dict)
    expected_delta_w: float = 0.0
    needs_approval_from: str | None = None
    status: Literal["proposed", "pending_approval", "approved", "refused", "executed", "reverted"] = "proposed"


class Plan(BaseModel):
    id: str = Field(default_factory=lambda: new_id("plan"))
    request_id: str
    actions: list[Action]
    expected_w: float
    feasible: bool
    shortfall_w: float = 0.0
    tradeoffs: list[str] = Field(default_factory=list)
    rationale: str = ""  # written by the LLM for a human operator


class Approval(BaseModel):
    plan_id: str
    action_rung: int
    approver: str
    decision: Literal["approved", "refused"]
    reason: str = ""
    t: float = Field(default_factory=now)


class TimelineEvent(BaseModel):
    t: float = Field(default_factory=now)
    kind: Literal[
        # dispatcher edition (SPEC §3)
        "grid", "policy", "event", "schedule", "plan", "approval", "action", "power",
        "latency", "state", "shortfall", "report", "note",
        # facility-throttle edition, kept for the existing tests
        "sample", "request", "baseline",
    ]
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Dispatcher edition (SPEC.md §3). The classes above are the original contract; these extend it.
# ---------------------------------------------------------------------------

Objective = Literal["cost", "carbon", "balanced"]
Device = Literal["gpu", "cpu", "either"]
RunDevice = Literal["gpu", "cpu"]
JobState = Literal["pending", "running", "paused", "done", "dropped"]
EventSource = Literal["openadr", "text", "ui"]

Point = tuple[datetime, float]  # (slot_start, value)


class GridSignal(BaseModel):
    """One snapshot of the grid as the dispatcher sees it. Every number carries its source and age."""

    iso: str
    location: str
    t: float = Field(default_factory=now)
    price_now: float = Field(description="$/MWh, latest real-time interval")
    price_interval_start: datetime | None = None
    price_curve: list[Point] = Field(default_factory=list, description="$/MWh per slot, next 24 h")
    price_curve_source: str = ""  # e.g. "DAY_AHEAD_HOURLY" or "last RT held flat"
    load_forecast: list[Point] = Field(default_factory=list, description="MW per hour")
    carbon_now: float | None = Field(default=None, description="gCO2/kWh from the live fuel mix")
    carbon_curve: list[Point] = Field(default_factory=list)
    carbon_curve_is_proxy: bool = False
    fuel_mix_mw: dict[str, float] = Field(default_factory=dict)
    alerts: list[str] = Field(default_factory=list)
    feed_age_s: float = 0.0
    stale: bool = False
    source_urls: list[str] = Field(default_factory=list)


class Job(BaseModel):
    id: str
    kind: WorkloadKind
    owner: str
    priority: int = Field(ge=1, description="1 = most important")
    energy_kwh_est: float | None = Field(default=None, description="measured W x expected runtime")
    measured_w: float | None = Field(default=None, description="delta above idle, from make calibrate")
    min_concurrency: int = 1
    max_concurrency: int = 1
    deadline: datetime | None = None
    required_runtime_min: int | None = Field(default=None, description="derived: remaining work / measured rate")
    target_steps: int | None = None
    interruptible: bool = True
    checkpoint_interval_s: int | None = None
    device: Device = "either"
    sla: dict[str, Any] = Field(default_factory=dict)
    state: JobState = "pending"
    progress: dict[str, Any] = Field(default_factory=dict)


class Policy(BaseModel):
    objective: Objective = "balanced"
    weights: dict[str, float] = Field(default_factory=dict)
    power_cap_w: float | None = None
    sla: dict[str, Any] = Field(default_factory=dict)
    never_pause: list[str] = Field(default_factory=list)
    approvals: dict[str, str] = Field(default_factory=dict)
    operator: str = ""
    slot_minutes: int = 15
    horizon_hours: int = 24
    solver_time_limit_s: float = 2.0


class CapEvent(BaseModel):
    """A power cap from OpenADR or plain text. target_w or target_pct (reduction vs baseline)."""

    id: str = Field(default_factory=lambda: new_id("cap"))
    source: EventSource
    start: datetime
    duration_s: int
    target_w: float | None = None
    target_pct: float | None = None
    reason: str = ""
    raw: str = ""


class SlotAssignment(BaseModel):
    run: bool
    concurrency: int = 0
    device: RunDevice | None = None


class DeadlineMiss(BaseModel):
    job_id: str
    deadline: datetime
    finishes_at: datetime | None
    slip_min: int


class Shortfall(BaseModel):
    """The minimal relaxation when the model is infeasible; what the negotiator takes to a human."""

    kind: Literal["deadline", "cap", "sla"]
    job_id: str | None = None
    amount: float = 0.0  # minutes of slip, or watts over the cap
    message: str = ""


class Schedule(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sched"))
    solve_t: float = Field(default_factory=now)
    slot_minutes: int
    slots: list[datetime] = Field(description="slot start times, horizon order")
    assignments: dict[str, list[SlotAssignment]] = Field(description="job id -> one entry per slot")
    objective_value: float = 0.0
    cost_usd: float = 0.0
    co2_g: float = 0.0
    deadline_misses: list[DeadlineMiss] = Field(default_factory=list)
    shortfalls: list[Shortfall] = Field(default_factory=list)
    explanations: list[str] = Field(default_factory=list, description="solver-derived facts only")
    planned_w: list[float] = Field(default_factory=list,
                                   description="machine W per slot from calibrated deltas (planned, not measured)")
    caps_w: list[float | None] = Field(default_factory=list)
    solver_status: str = ""
    solve_wall_s: float = 0.0
    relaxed: bool = False
    on_stale_data: bool = False


class PowerReading(BaseModel):
    """One powermetrics sample. SoC power as reported by macOS, in watts. Measured, not estimated."""

    t: float = Field(default_factory=now)
    cpu_w: float | None = None
    gpu_w: float | None = None
    ane_w: float | None = None
    combined_w: float
    fields: list[str] = Field(default_factory=list, description="which powermetrics fields existed")
    source: Literal["powermetrics"] = "powermetrics"


class DevicePower(BaseModel):
    """What `make calibrate` measured for one job on one device. Watts are deltas above idle."""

    delta_w: float
    rate: float | None = Field(default=None, description="work units/s (train steps, batch items)")
    concurrency: int | None = Field(default=None, description="chat: concurrency the delta was measured at")
    samples: int = 0


class Calibration(BaseModel):
    measured_at: float
    machine: str
    idle_w: float
    window_s: int
    jobs: dict[str, dict[str, DevicePower]] = Field(description="job id -> device -> measured power")
    source: Literal["powermetrics"] = "powermetrics"
