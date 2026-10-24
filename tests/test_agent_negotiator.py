"""agent/negotiator.py: DEMO.md 1:45 on fixtures. The LLM is a labelled test fake."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.negotiator import draft_ask, parse_deadline, parse_reply
from core.types import Job, Shortfall
from tests.test_agent_llm import ScriptedLLM

PDT = timezone(timedelta(hours=-7))
NOW = datetime(2026, 10, 24, 14, 5, tzinfo=PDT)  # Saturday
TRAIN = Job(id="train", kind="deferrable", owner="ml-team", priority=2,
            deadline=datetime(2026, 10, 26, 9, 0, tzinfo=PDT))
SHORT = Shortfall(kind="deadline", job_id="train", amount=95, message="train needs 95 more min of GPU time")


async def test_draft_ask_offline_uses_facts():
    ask = await draft_ask(SHORT, TRAIN, ScriptedLLM())
    assert ask.owner == "ml-team" and ask.job_id == "train" and ask.status == "pending"
    assert "95 min" in ask.message and "Mon Oct 26 09:00" in ask.message


async def test_draft_ask_rejects_invented_numbers():
    ask = await draft_ask(SHORT, TRAIN, ScriptedLLM("ml-team, train would be 3 hours late. OK?"))
    assert "95 min" in ask.message  # fell back to the template


async def test_draft_ask_accepts_grounded_rewrite():
    text = "Hi ml-team: holding the grid cap pushes train about 95 min past Mon Oct 26 09:00. Yes, no, or later?"
    ask = await draft_ask(SHORT, TRAIN, ScriptedLLM(text))
    assert ask.message == text


async def test_demo_refusal_with_reason():
    ask = await draft_ask(SHORT, TRAIN, ScriptedLLM())
    llm = ScriptedLLM()
    d = await parse_reply(ask, "no, this has to finish by 9 AM Monday", llm, NOW)
    assert d.decision == "refuse" and d.reason == "this has to finish by 9 AM Monday"
    assert not d.llm_used and not llm.calls and d.request_id == ask.id


async def test_counter_offer_new_deadline():
    ask = await draft_ask(SHORT, TRAIN, ScriptedLLM())
    d = await parse_reply(ask, "ok if it's done by Tuesday noon", ScriptedLLM(), NOW)
    assert d.decision == "new_deadline" and d.new_deadline == datetime(2026, 10, 27, 12, 0, tzinfo=PDT)


async def test_plain_yes_no():
    ask = await draft_ask(SHORT, TRAIN, ScriptedLLM())
    assert (await parse_reply(ask, "Yes, go ahead.", ScriptedLLM(), NOW)).decision == "approve"
    assert (await parse_reply(ask, "nope", ScriptedLLM(), NOW)).decision == "refuse"


async def test_messy_reply_uses_llm_and_validates():
    ask = await draft_ask(SHORT, TRAIN, ScriptedLLM())
    llm = ScriptedLLM({"decision": "new_deadline", "new_deadline": "2026-10-27T18:00:00-07:00",
                       "reason": "we can live with Tuesday evening"})
    d = await parse_reply(ask, "hmm, we can live with Tuesday evening I guess", llm, NOW)
    assert d.llm_used and d.decision == "new_deadline" and d.new_deadline.hour == 18
    past = ScriptedLLM({"decision": "new_deadline", "new_deadline": "2026-10-20T18:00:00-07:00"})
    assert (await parse_reply(ask, "hmm, last week would do", past, NOW)).decision == "unclear"


async def test_offline_reply_unclear():
    ask = await draft_ask(SHORT, TRAIN, ScriptedLLM())
    d = await parse_reply(ask, "let me check with the team", ScriptedLLM(), NOW)
    assert d.decision == "unclear" and d.reason == "agent offline" and not d.llm_used


def test_parse_deadline_forms():
    assert parse_deadline("9 AM Monday", NOW) == datetime(2026, 10, 26, 9, 0, tzinfo=PDT)
    assert parse_deadline("tomorrow at 5pm", NOW) == datetime(2026, 10, 25, 17, 0, tzinfo=PDT)
    assert parse_deadline("Saturday noon", NOW) == datetime(2026, 10, 31, 12, 0, tzinfo=PDT)
    assert parse_deadline("Tuesday 9", NOW) is None
