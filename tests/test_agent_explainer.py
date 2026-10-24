"""agent/explainer.py on the real captured schedule (tests/fixtures/real_timeline_solve_20261023.jsonl).
The LLM is a labelled test fake; the test proves no invented number survives."""
from __future__ import annotations

import json
from pathlib import Path

from agent.explainer import explain, grid_facts, numbers, ungrounded
from core.types import GridSignal, Schedule
from tests.test_agent_llm import ScriptedLLM

TIMELINE = Path(__file__).parent / "fixtures" / "real_timeline_solve_20261023.jsonl"
EVENTS = [json.loads(line) for line in TIMELINE.read_text().splitlines()]
SIGNAL = GridSignal.model_validate(next(e["data"] for e in EVENTS if e["kind"] == "grid"))
SCHEDULE = Schedule.model_validate(next(e["data"] for e in EVENTS if e["kind"] == "schedule"))
FACTS = grid_facts(SIGNAL) + SCHEDULE.explanations


async def test_grounded_llm_text_accepted():
    text = ("Training moves to Sat 14:00-16:00, where power averages $5.32/MWh against $36.33/MWh in the slots "
            "it skips, and batch takes the 14:45-15:00 slot. Chat keeps running in every slot at concurrency 4.")
    e = await explain(SCHEDULE, SIGNAL, ScriptedLLM(text))
    assert e.llm_used and e.text == text and e.facts == SCHEDULE.explanations


async def test_rounded_numbers_allowed():
    text = "Training runs Sat 14:00-16:00 at about $5/MWh versus $36/MWh. Chat stays at concurrency 4."
    assert (await explain(SCHEDULE, SIGNAL, ScriptedLLM(text))).llm_used


async def test_invented_number_rejected():
    text = ("Training runs Sat 14:00-16:00 at $5.32/MWh, saving 85% on energy. "
            "Chat stays on at concurrency 4.")
    assert ungrounded(text, FACTS) == {"85"}
    e = await explain(SCHEDULE, SIGNAL, ScriptedLLM(text))
    assert not e.llm_used and "85" not in e.text


async def test_offline_fallback_is_grounded():
    e = await explain(SCHEDULE, SIGNAL, ScriptedLLM())
    assert not e.llm_used and not ungrounded(e.text, FACTS)
    assert "$48.68/MWh" in e.text and "$5.32/MWh" in e.text
    assert numbers(e.text) <= numbers(" ".join(FACTS))
