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


def test_busy_chat_keeps_full_concurrency_under_cap_and_training_moves_instead():
    # cap 16 W: 1 W idle + train 12 W fits only if chat draws little. Chat is 2 W per stream (8 W at 4).
    capped = POLICY.model_copy(update={"power_cap_w": 16.0})
    quiet = solve(signal([50.0] * 96), jobs(), capped, CAL, chat_busy=0.2)
    assert all(a.concurrency == 4 for a in quiet.assignments["chat"])
    assert any(a.run for a in quiet.assignments["train"])
    assert all(w <= 16.0 + 1e-6 for w in quiet.planned_w)
    assert quiet.chat_busy_streams == 0.2
    busy = solve(signal([50.0] * 96), jobs(), capped, CAL, chat_busy=4.0)
    assert all(w <= 16.0 + 1e-6 for w in busy.planned_w)
    # with 4 busy streams chat alone is 8 W; degrading chat is the operator's call, so training moves to the CPU
    assert all(a.concurrency == 4 for a in busy.assignments["chat"])
    on = [i for i, a in enumerate(busy.assignments["train"]) if a.run]
    assert on and all(busy.assignments["train"][i].device == "cpu" for i in on)


def test_chat_is_degraded_only_with_the_operators_approval():
    # regression (evidence-chat, Sat 09:49): under a cap the plan cut chat to 1 stream on its own, requests
    # queued and time to first token reached 4.5 s. 1 W idle + 8 W of busy chat cannot fit 6 W; 2 streams would.
    cap = [CapEvent(source="ui", start=SLOTS[0], duration_s=3600, target_w=6.0)]
    held = solve(signal([50.0] * 96), jobs(), POLICY, CAL, events=cap, chat_busy=4.0)
    assert all(a.concurrency == 4 for a in held.assignments["chat"])
    assert any(f.kind == "cap" for f in held.shortfalls)
    sla = next(f for f in held.shortfalls if f.kind == "sla")
    assert sla.job_id == "chat" and sla.amount == pytest.approx(6.0)
    assert "from 4 streams at a time to 1" in sla.message and "queue" in sla.message
    ok = solve(signal([50.0] * 96), jobs(), POLICY, CAL, events=cap, chat_busy=4.0, chat_degrade_approved=True)
    assert not ok.relaxed and not ok.shortfalls
    conc = [a.concurrency for a in ok.assignments["chat"]]
    assert conc[:4] == [2] * 4 and set(conc[4:]) == {4}          # only as far as the cap needs, only while it lasts
    assert all(w <= 6.0 + 1e-6 for w in ok.planned_w[:4])


def test_chat_watts_follow_the_measured_curve():
    from dispatcher.model import chat_w
    curve = CAL.model_copy(update={"jobs": {**CAL.jobs, "chat": {"gpu": DevicePower(
        delta_w=8.0, concurrency=4, streams_w={1: 6.0, 2: 7.0, 4: 8.0})}}})
    chat = jobs()[0]
    assert [chat_w(chat, curve, n) for n in (0, 0.5, 1, 2, 3, 4, 5)] == pytest.approx([0, 3, 6, 7, 7.5, 8, 8.5])
    assert chat_w(chat, CAL, 2) == pytest.approx(4.0)          # one measured point: a straight line through it
    s = solve(signal([50.0] * 96), [chat], POLICY, curve, chat_busy=2.0)
    assert s.planned_w[0] == pytest.approx(1.0 + 7.0)          # idle + two busy streams, not half of four
    # degrading from 4 to 1 at 2 busy streams saves only the 2-to-1 step of the curve
    held = solve(signal([50.0] * 96), [chat], POLICY.model_copy(update={"power_cap_w": 7.5}), curve, chat_busy=2.0)
    assert next(f for f in held.shortfalls if f.kind == "sla").amount == pytest.approx(1.0)


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
def test_refused_slip_holds_the_cap_until_the_operator_approves_going_over():
    # train needs 90 min of GPU before 2 h; under a 10 W cap only CPU training fits (1 W idle + 6 W), too slow
    dl = SLOTS[8]
    capped = POLICY.model_copy(update={"power_cap_w": 10.0})
    free = solve(signal([50.0] * 96), jobs(train_deadline=dl), capped, CAL, chat_busy=0.0)
    assert free.relaxed and any(f.kind == "deadline" and f.job_id == "train" for f in free.shortfalls)
    assert all(w <= 10.0 + 1e-6 for w in free.planned_w)          # nobody approved anything: cap holds
    # owner refused: the deadline may not bend in the options offered, but until the operator approves
    # going over, the running plan still holds the cap (train slips meanwhile)
    kept = solve(signal([50.0] * 96), jobs(train_deadline=dl), capped, CAL, chat_busy=0.0,
                 hard_deadlines=frozenset({"train"}))
    assert not any(f.kind == "deadline" and f.job_id == "train" for f in kept.shortfalls)
    assert any(f.kind == "cap" for f in kept.shortfalls)
    assert all(w <= 10.0 + 1e-6 for w in kept.planned_w) and kept.deadline_misses
    assert any("cap held" in e for e in kept.explanations)
    approved = solve(signal([50.0] * 96), jobs(train_deadline=dl), capped, CAL, chat_busy=0.0,
                     hard_deadlines=frozenset({"train"}), exceed_cap_approved=True)
    assert not approved.deadline_misses and max(approved.planned_w) > 10.0
    assert any("approved by the operator" in e for e in approved.explanations)


def test_cap_bends_without_approval_only_when_nothing_fits():
    s = solve(signal([50.0] * 96), jobs(), POLICY.model_copy(update={"power_cap_w": 0.5}), CAL, chat_busy=0.0)
    assert any("nothing fits under it" in e for e in s.explanations)


def test_background_load_counts_against_the_cap():
    # cheap capped hour: 1 W idle + 8 W chat + 6 W CPU training = 15 W fits 15.5 W; 1 W of load outside the plan does not
    from core.types import CapEvent
    cap = [CapEvent(source="ui", start=SLOTS[0], duration_s=3600, target_w=15.5)]
    prices = [5.0] * 4 + [50.0] * 92
    js = [j for j in jobs() if j.id != "batch"]
    s = solve(signal(prices), js, POLICY, CAL, events=cap)
    assert set(run_slots(s, "train")) & {0, 1, 2, 3} and s.background_w == 0.0
    s = solve(signal(prices), js, POLICY, CAL, events=cap, background_w=1.0)
    assert not set(run_slots(s, "train")) & {0, 1, 2, 3} and s.background_w == 1.0 and not s.relaxed
    assert all(s.planned_w[i] <= 15.5 + 1e-6 for i in range(4)) and s.planned_w[0] == pytest.approx(10.0)
    assert any("measured load outside the plan: 1.00 W" in f for f in s.explanations)


def test_negative_background_never_loosens_the_cap():
    from core.types import CapEvent
    cap = [CapEvent(source="ui", start=SLOTS[0], duration_s=3600, target_w=14.5)]
    prices = [5.0] * 4 + [50.0] * 92
    js = [j for j in jobs() if j.id != "batch"]
    a = solve(signal(prices), js, POLICY, CAL, events=cap)
    b = solve(signal(prices), js, POLICY, CAL, events=cap, background_w=-5.0)
    assert a.solver_status == b.solver_status == "OPTIMAL"
    assert a.assignments == b.assignments and a.planned_w == b.planned_w and b.background_w == 0.0
    assert not set(run_slots(b, "train")) & {0, 1, 2, 3}      # 15 W of CPU training never fits 14.5 W
