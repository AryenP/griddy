"""agent/negotiator.draft_operator_ask (DEMO.md 3:00, "ask for 90%") on schedules from the real solver.
The calibration and prices are the dispatcher tests' labelled test fixtures; the LLM is a test fake."""
from __future__ import annotations

import pytest

from agent.explainer import numbers, ungrounded
from agent.negotiator import CAP_JOB, draft_operator_ask
from dispatcher.solve import solve
from tests.test_agent_llm import ScriptedLLM
from tests.test_dispatcher import CAL, POLICY, SLOTS, jobs, signal

REFUSED = {"train": "this has to finish by 9 AM Monday"}


@pytest.fixture(scope="module")
def refused_slip():
    """The owner refused train's slip: the solver keeps the deadline and bends the cap."""
    return solve(signal([50.0] * 96), jobs(train_deadline=SLOTS[8]), POLICY.model_copy(update={"power_cap_w": 10.0}),
                 CAL, chat_busy=0.0, hard_deadlines=frozenset({"train"}))


@pytest.fixture(scope="module")
def below_floor():
    """The 90% ask: the cap is under what chat alone needs, so no deadline slip helps."""
    return solve(signal([50.0] * 96), jobs(), POLICY.model_copy(update={"power_cap_w": 2.0}), CAL)


def _cap(s):
    return next(sf for sf in s.shortfalls if sf.kind == "cap")


async def test_offline_refused_slip_offers_exactly_the_proved_options(refused_slip):
    s = refused_slip
    ask = await draft_operator_ask(s.shortfalls, s, ScriptedLLM(), "ops", refused=REFUSED)
    cap = _cap(s)
    assert ask.job_id == CAP_JOB and ask.owner == "ops" and ask.shortfall == cap and ask.status == "pending"
    m = ask.message
    assert m.startswith("ops: the power cap cannot be held.")
    assert f"{cap.amount:.2f} W" in m and "Approve going over the cap" in m and "reply no" in m
    assert "refused by its owner" in m and "9 AM Monday" in m and "train" in m
    # the running plan holds the cap while the operator decides, so no slot is described as over it
    assert all(w <= c + 1e-6 for w, c in zip(s.planned_w, s.caps_w) if c is not None)
    assert "plan needs" not in m
    # every number is copied from the solver's facts or the owner's words
    floor = min(w for w, c in zip(s.planned_w, s.caps_w) if c is not None)
    facts = [cap.message, REFUSED["train"], f"{cap.amount:.2f}", f"{max(s.planned_w):.1f}", f"{floor:.1f}",
             "10.0"] + \
            [f"{t:%H:%M}" for t in s.slots] + [str(a.concurrency) for a in s.assignments["chat"]]
    assert not ungrounded(m, facts)


async def test_offline_below_floor_says_no_slip_helps(below_floor):
    s = below_floor
    assert not [sf for sf in s.shortfalls if sf.kind == "deadline"]
    ask = await draft_operator_ask(s.shortfalls, s, ScriptedLLM(), "ops")
    assert "No deadline slip closes the gap." in ask.message
    assert "cap is 2.0 W" in ask.message and f"{_cap(s).amount:.2f} W" in ask.message
    capped = [i for i, c in enumerate(s.caps_w) if c is not None]
    floor = min(s.planned_w[i] for i in capped)   # chat protected, everything else off
    assert f"The lowest the plan goes while the cap holds is {floor:.1f} W" in ask.message
    assert not ungrounded(ask.message, [sf.message for sf in s.shortfalls] + [f"{floor:.1f}", f"{max(s.planned_w):.1f}", "2.0"]
                          + [f"{t:%H:%M}" for t in s.slots] + [str(a.concurrency) for a in s.assignments["chat"]])


async def test_grounded_rewrite_accepted(refused_slip):
    s = refused_slip
    cap = _cap(s)
    text = (f"ops, holding the cap would break train's deadline, which its owner refused. "
            f"Approve going up to {cap.amount:.2f} W over the cap for this event, or say no and why.")
    ask = await draft_operator_ask(s.shortfalls, s, ScriptedLLM(text), "ops", refused=REFUSED)
    assert ask.message == text


async def test_rewrite_with_invented_number_falls_back(refused_slip):
    s = refused_slip
    llm = ScriptedLLM(f"ops: you can reach 47% if chat goes dark. Approve {_cap(s).amount:.2f} W over?")
    ask = await draft_operator_ask(s.shortfalls, s, llm, "ops", refused=REFUSED)
    assert "47" not in ask.message and ask.message.startswith("ops: the power cap cannot be held.")


async def test_rewrite_dropping_the_amount_falls_back(refused_slip):
    s = refused_slip
    ask = await draft_operator_ask(s.shortfalls, s, ScriptedLLM("ops: the cap is tight. Approve going over?"),
                                   "ops", refused=REFUSED)
    assert f"{_cap(s).amount:.2f} W" in ask.message


async def test_rewrite_offering_a_knob_falls_back(refused_slip):
    s = refused_slip
    llm = ScriptedLLM(f"ops: approve {_cap(s).amount:.2f} W over the cap, or I can pause chat instead.")
    ask = await draft_operator_ask(s.shortfalls, s, llm, "ops", refused=REFUSED)
    assert "pause chat" not in ask.message


async def test_needs_a_cap_shortfall(refused_slip):
    deadline_only = [sf for sf in refused_slip.shortfalls if sf.kind != "cap"]
    with pytest.raises(ValueError):
        await draft_operator_ask(deadline_only, refused_slip, ScriptedLLM(), "ops")


def test_numbers_helper_sees_clock_times():
    assert numbers("from 14:15, 4.20 W") == {"14:15", "4.20"}


async def test_operator_ask_says_what_a_no_does_to_chat():
    """Busy chat over the cap: chat keeps full concurrency until the operator answers, and the ask says what
    degrading it would save, so a no is informed consent (policy approvals.chat_degrade)."""
    s = solve(signal([50.0] * 96), jobs(), POLICY.model_copy(update={"power_cap_w": 6.0}), CAL, chat_busy=4.0)
    req = await draft_operator_ask(s.shortfalls, s, ScriptedLLM(), "ops")
    assert "Chat keeps full concurrency until you say otherwise" in req.message
    assert "6.00 W" in req.message and "after a no, chat is degraded" in req.message
    dropped = ScriptedLLM(f"ops: the cap cannot be held; approve going over by up to {_cap(s).amount:.2f} W?")
    req = await draft_operator_ask(s.shortfalls, s, dropped, "ops")
    assert "Chat keeps full concurrency" in req.message            # a rewrite that drops the chat consequence is not used

