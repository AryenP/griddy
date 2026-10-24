"""DEMO.md 1:15-2:30 through the agent bridge with the agent OFFLINE (no key), so the deterministic
paths run: regex intake, template asks, regex replies, facts-only explanations. TEST FIXTURES: the
calibration, jobs and prices from tests/test_dispatcher.py; time is moved by monkeypatch."""
from datetime import timedelta

import pytest

import controller.execute as ex
import workloads.base as base
from api.agent_bridge import CAP_JOB, AgentBridge
from controller.knobs import Knobs
from core.timeline import Timeline
from core.types import CapEvent, PowerReading
from tests.test_dispatcher import CAL, POLICY, SLOTS, jobs, signal


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("AZURE_AI_PROJECT_ENDPOINT", "")
    monkeypatch.setattr(base, "CONTROL_DIR", tmp_path / "ctl")
    clock = {"t": SLOTS[0].timestamp() + 30}
    monkeypatch.setattr(ex.time, "time", lambda: clock["t"])
    monkeypatch.setattr(ex, "load_jobs", lambda cal: jobs(train_deadline=SLOTS[8]))
    monkeypatch.setattr(ex.Executor, "chat_busy", staticmethod(lambda: 0.0))
    tl = Timeline(run_id="a", root=tmp_path)
    e = ex.Executor(tl, Knobs(tl), CAL, POLICY.model_copy(update={"operator": "ops"}))
    for k in range(60):                                   # 60 s of measured baseline at 20 W
        e.on_power(PowerReading(t=clock["t"] - 60 + k, combined_w=20.0))
    return e, AgentBridge(tl, e), tl, tmp_path


async def test_operator_text_to_owner_refusal_to_operator_approval(rig):
    e, agent, tl, tmp = rig
    assert agent.status == "offline"
    await e.on_signal(signal([50.0] * 96))
    assert agent.explanation is not None and not agent.explanation.llm_used

    # 1:15 the utility, in plain words: 50% off (20 W baseline -> 10 W) for two hours
    result, sched = await agent.request("grid alert, I need 50% off for the next 2 hours", "judge")
    assert result.kind == "cap_event" and not result.llm_used and result.readback
    assert sched.relaxed                                  # train cannot make its deadline under 10 W

    # the solver's cheaper option (slip train) goes to the owner first; the operator is not asked yet
    asks = agent.pending()
    assert [a.job_id for a in asks] == ["train"] and asks[0].owner == "ml"
    assert e.plan.needs_approval == [asks[0].id]

    # 1:45 the owner refuses in words: the deadline turns hard in the options, the operator is asked,
    # and until the operator answers the running plan keeps holding the cap (train slips meanwhile)
    decision, sched = await agent.reply(asks[0].id, "no, this has to finish by 9 AM Monday", "owner")
    assert decision.decision == "refuse" and "9 AM Monday" in decision.reason
    assert "train" in e.hard_deadlines
    assert any(f.kind == "cap" for f in sched.shortfalls)
    assert all(w <= c + 1e-6 for w, c in zip(sched.planned_w, sched.caps_w) if c is not None)
    ops = agent.pending()
    assert [a.job_id for a in ops] == [CAP_JOB] and ops[0].owner == "ops"
    assert "9 AM Monday" in ops[0].message or "refused" in ops[0].message.lower()   # the owner's reason carries over

    # the operator approves going over the cap: only now does the plan exceed it, and the deadline holds
    decision, sched = await agent.reply(ops[0].id, "yes", "judge")
    assert decision.decision == "approve" and agent.approvals[ops[0].id].status == "approved"
    assert not sched.deadline_misses
    assert any(w > c + 1e-6 for w, c in zip(sched.planned_w, sched.caps_w) if c is not None)
    kinds = [ev.kind for ev in Timeline.read(tl.path)]
    assert kinds.count("approval") >= 5 and "event" in kinds


async def test_owner_counteroffer_moves_the_deadline(rig):
    e, agent, _, _ = rig
    await e.on_signal(signal([50.0] * 96))
    await agent.request("cap at 10 W for 2 hours", "judge")
    ask = agent.pending()[0]
    decision, sched = await agent.reply(ask.id, "ok if it's done by Saturday 6 PM", "owner")
    assert decision.decision == "new_deadline" and decision.new_deadline
    assert e.jobs()[1].deadline == decision.new_deadline
    assert agent.approvals[ask.id].status == "countered"


async def test_unclear_text_asks_one_question_and_changes_nothing(rig):
    e, agent, _, _ = rig
    await e.on_signal(signal([50.0] * 96))
    before = e.schedule.id
    result, sched = await agent.request("can you help with the grid thing", "judge")
    assert result.kind == "clarify" and result.question and sched is None and e.schedule.id == before



async def test_operator_question_answered_from_live_state(rig):
    e, agent, tl, _ = rig
    await e.on_signal(signal([50.0] * 96))
    agent.snapshot = lambda: {"schedule": e.schedule.model_dump(mode="json"), "plan": e.plan.model_dump(mode="json"),
                              "policy": e.policy.model_dump(mode="json"), "approvals": [], "jobs": {}}
    ans = await agent.ask("why is training paused?")
    assert ans.text and not ans.llm_used
    refused = await agent.ask("pause chat now")
    assert refused.text and not refused.llm_used



async def test_operator_refusal_keeps_the_cap_and_is_not_asked_again(rig):
    e, agent, _, _ = rig
    await e.on_signal(signal([50.0] * 96))
    await agent.request("grid alert, I need 50% off for the next 2 hours", "judge")
    await agent.reply(agent.pending()[0].id, "no, it has to finish on time", "owner")
    op = agent.pending()[0]
    _, sched = await agent.reply(op.id, "no, the utility's limit comes first", "judge")
    assert agent.approvals[op.id].status == "refused" and not agent.pending()
    await e.resolve("re-check")
    assert not agent.pending()                                   # same caps: the operator is not asked again
    assert all(w <= c + 1e-6 for w, c in zip(e.schedule.planned_w, e.schedule.caps_w) if c is not None)


async def test_operator_refusal_lets_busy_chat_degrade_toward_the_cap(rig, monkeypatch):
    """A no to going over the cap is the operator's call on chat too (approvals.chat_degrade): before it chat
    keeps full concurrency over the cap, after it the plan may degrade chat for exactly these caps."""
    e, agent, _, _ = rig
    monkeypatch.setattr(type(e), "chat_busy", staticmethod(lambda: 4.0))
    await e.on_signal(signal([50.0] * 96))
    await e.add_event(CapEvent(source="ui", start=SLOTS[0], duration_s=3600, target_w=6.0))
    assert all(a.concurrency == 4 for a in e.schedule.assignments["chat"])
    assert max(e.schedule.planned_w[:4]) == pytest.approx(9.0)   # 1 W idle + 8 W of busy chat: over, and asked
    for a in [a for a in agent.pending() if a.job_id == "train"]:     # the owner is asked first, if a slip helps
        await agent.reply(a.id, "no, it has to finish on time", "owner")
    op = next(a for a in agent.pending() if a.job_id == "power_cap")
    assert "after a no, chat is degraded" in op.message
    _, sched = await agent.reply(op.id, "no, hold the limit", "judge")
    assert sched is not None and e.cap_key() in e.cap_held
    assert [a.concurrency for a in sched.assignments["chat"][:4]] == [2] * 4
    assert all(w <= 6.0 + 1e-6 for w in sched.planned_w[:4])

