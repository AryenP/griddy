"""Dispatcher tests (SPEC §12). TEST FIXTURES ONLY: the calibration watts and price curves below
are invented for unit tests and never reach a judge; `make solve` uses measured calibration and
the live grid."""
from datetime import datetime, timedelta, timezone

import pytest

from core.types import Calibration, CapEvent, DevicePower, GridSignal, Job, Policy
from dispatcher.solve import solve

T0 = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
SLOTS = [T0 + timedelta(minutes=15 * i) for i in range(96)]

CAL = Calibration(measured_at=0, machine="test-fixture", idle_w=1.0, window_s=20, jobs={
    "chat": {"gpu": DevicePower(delta_w=8.0, concurrency=4)},
    "train": {"gpu": DevicePower(delta_w=12.0, rate=10.0), "cpu": DevicePower(delta_w=6.0, rate=2.5)},
    "batch": {"gpu": DevicePower(delta_w=5.0, rate=40.0), "cpu": DevicePower(delta_w=4.0, rate=20.0)},
})


def jobs(train_deadline=None, train_min=90, batch_min=45):
    return [
        Job(id="chat", kind="interactive", owner="ops", priority=1, interruptible=False, device="gpu",
            min_concurrency=1, max_concurrency=4),
        Job(id="train", kind="deferrable", owner="ml", priority=2, device="either",
            deadline=train_deadline, required_runtime_min=train_min),
        Job(id="batch", kind="droppable", owner="data", priority=3, device="either", required_runtime_min=batch_min),
    ]


def signal(prices, carbon=200.0):
    return GridSignal(iso="TEST", location="fixture", t=T0.timestamp(), price_now=prices[0],
                      price_curve=list(zip(SLOTS, prices)), carbon_curve=[(s, carbon) for s in SLOTS])


POLICY = Policy(objective="cost", never_pause=["chat"], slot_minutes=15, horizon_hours=24, solver_time_limit_s=5)


def run_slots(s, jid):
    return [i for i, a in enumerate(s.assignments[jid]) if a.run]


def test_cheap_slots_preferred():
    prices = [50.0] * 96
    for i in range(40, 52):
        prices[i] = 5.0                       # a 3-hour cheap window (midday solar)
    s = solve(signal(prices), jobs(), POLICY, CAL)
    assert set(run_slots(s, "train")) <= set(range(40, 52))
    assert set(run_slots(s, "batch")) <= set(range(40, 52))
    assert s.solver_status == "OPTIMAL"


def test_deadline_respected_even_when_later_is_cheaper():
    prices = [50.0] * 48 + [1.0] * 48         # cheap only after the deadline
    dl = SLOTS[24]                             # 6 h in
    s = solve(signal(prices), jobs(train_deadline=dl), POLICY, CAL)
    on = run_slots(s, "train")
    assert on and max(on) < 24
    assert not s.deadline_misses


def test_cap_respected_and_chat_never_paused():
    prices = [50.0] * 96
    s = solve(signal(prices), jobs(), POLICY.model_copy(update={"power_cap_w": 16.0}), CAL)
    assert all(w <= 16.0 + 1e-6 for w in s.planned_w)
    assert all(a.run and a.concurrency >= 1 for a in s.assignments["chat"])


def test_cap_event_pct_of_baseline():
    prices = [50.0] * 96
    ev = CapEvent(source="text", start=SLOTS[0], duration_s=3600, target_pct=30)
    s = solve(signal(prices), jobs(), POLICY, CAL, events=[ev], baseline_w=20.0)
    assert all(w <= 14.0 + 1e-6 for w in s.planned_w[:4])
    assert s.caps_w[4] is None


def test_infeasible_returns_minimal_relaxation_naming_train():
    prices = [50.0] * 96
    dl = SLOTS[4]                              # 1 h to do 90 min of GPU work: impossible
    s = solve(signal(prices), jobs(train_deadline=dl), POLICY, CAL)
    assert s.relaxed and s.solver_status.startswith("INFEASIBLE")
    slips = [f for f in s.shortfalls if f.kind == "deadline"]
    assert [f.job_id for f in slips] == ["train"]
    assert slips[0].amount == pytest.approx(30, abs=15)   # ~30 min short at GPU speed
    assert s.deadline_misses and s.deadline_misses[0].job_id == "train"


def test_cap_below_chat_floor_reports_cap_shortfall():
    s = solve(signal([50.0] * 96), jobs(), POLICY.model_copy(update={"power_cap_w": 2.0}), CAL)
    assert any(f.kind == "cap" for f in s.shortfalls)
    assert all(a.run for a in s.assignments["chat"])       # chat still never paused


def test_deterministic():
    prices = [float((i * 37) % 50 + 1) for i in range(96)]
    a = solve(signal(prices), jobs(), POLICY, CAL)
    b = solve(signal(prices), jobs(), POLICY, CAL)
    assert a.assignments == b.assignments


def test_idle_chat_keeps_full_concurrency_under_cap_busy_chat_does_not():
    # cap 16 W: 1 W idle + train 12 W fits only if chat draws little. Chat is 2 W per stream (8 W at 4).
    capped = POLICY.model_copy(update={"power_cap_w": 16.0})
    quiet = solve(signal([50.0] * 96), jobs(), capped, CAL, chat_busy=0.2)
    assert all(a.concurrency == 4 for a in quiet.assignments["chat"])
    assert any(a.run for a in quiet.assignments["train"])
    assert all(w <= 16.0 + 1e-6 for w in quiet.planned_w)
    assert quiet.chat_busy_streams == 0.2
    busy = solve(signal([50.0] * 96), jobs(), capped, CAL, chat_busy=4.0)
    assert all(w <= 16.0 + 1e-6 for w in busy.planned_w)
    # with 4 busy streams chat alone is 8 W: train (12 W GPU / 6 W CPU) can only fit by squeezing chat
    on = [i for i, a in enumerate(busy.assignments["train"]) if a.run]
    assert all(busy.assignments["chat"][i].concurrency < 4 or busy.assignments["train"][i].device == "cpu" for i in on)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="asyncio signal handlers are POSIX-only")
async def test_solve_in_a_thread_keeps_the_runtimes_sigint_handler():
    """Regression (Sat 01:35): CP-SAT's own Ctrl-C catching, from a worker thread, left SIGINT at the
    default action, so Ctrl-C killed the runtime without its shutdown. If this regresses, pytest itself
    dies with exit code 130, which is loud on purpose."""
    import asyncio
    import os
    import signal as sg
    loop = asyncio.get_running_loop()
    got = asyncio.Event()
    loop.add_signal_handler(sg.SIGINT, got.set)
    try:
        await asyncio.to_thread(solve, signal([50.0] * 96), jobs(), POLICY, CAL)
        os.kill(os.getpid(), sg.SIGINT)
        await asyncio.wait_for(got.wait(), 2)
    finally:
        loop.remove_signal_handler(sg.SIGINT)
def test_refused_slip_keeps_deadline_and_bends_the_cap():
    # train needs 90 min of GPU before 2 h; under a 10 W cap only CPU training fits (1 W idle + 6 W), too slow
    dl = SLOTS[8]
    capped = POLICY.model_copy(update={"power_cap_w": 10.0})
    free = solve(signal([50.0] * 96), jobs(train_deadline=dl), capped, CAL, chat_busy=0.0)
    assert free.relaxed and any(f.kind == "deadline" and f.job_id == "train" for f in free.shortfalls)
    kept = solve(signal([50.0] * 96), jobs(train_deadline=dl), capped, CAL, chat_busy=0.0,
                 hard_deadlines=frozenset({"train"}))
    assert not any(f.kind == "deadline" and f.job_id == "train" for f in kept.shortfalls)
    assert any(f.kind == "cap" for f in kept.shortfalls)
    assert not kept.deadline_misses                       # the refused deadline holds
    assert max(kept.planned_w) > 10.0                      # by going over the cap, which needs approval
