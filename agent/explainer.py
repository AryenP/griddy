"""Two sentences an operator reads, reworded from the solver's facts and the grid signal. The explainer does
not decide anything, and it rejects its own output if any number in it is not in the input facts."""
from __future__ import annotations

import re
from datetime import datetime

from opentelemetry import trace

from agent.llm import LLM, AgentOffline
from core.types import Explanation, GridSignal, Schedule

tracer = trace.get_tracer("brownout.agent")

# Clock times (14:00), then plain numbers with optional thousands separators and decimals.
_NUMBER = re.compile(r"\d{1,2}:\d{2}|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def allowed_numbers(facts: list[str]) -> set[str]:
    """Every number in the facts, plus the same number rounded to fewer decimals (36.33 -> 36.3, 36)."""
    out: set[str] = set()
    for tok in numbers(" ".join(facts)):
        out.add(tok)
        if ":" in tok:
            continue
        plain = tok.replace(",", "")
        out.add(plain)
        if "." in plain:
            value, places = float(plain), len(plain.split(".")[1])
            out.update(f"{value:.{p}f}" for p in range(places))
            out.add(f"{round(value):,}")
        elif len(plain) > 3:
            out.add(f"{int(plain):,}")
    return out


def ungrounded(text: str, facts: list[str]) -> set[str]:
    """Numbers in `text` that do not appear in `facts` (empty set = grounded)."""
    allowed = allowed_numbers(facts)
    return {tok for tok in numbers(text) if tok not in allowed and tok.replace(",", "") not in allowed}


def _hhmm(t: datetime | None) -> str:
    return f"{t:%H:%M}" if t else "unknown time"


def grid_facts(signal: GridSignal) -> list[str]:
    """The grid signal as plain fact lines, each with its source and age."""
    facts = [(f"{signal.iso} {signal.location} real-time price ${signal.price_now:.2f}/MWh for the interval "
              f"starting {_hhmm(signal.price_interval_start)}, feed age {signal.feed_age_s:.0f} s")]
    if signal.carbon_now is not None:
        facts.append(f"grid carbon intensity {signal.carbon_now:.0f} gCO2/kWh from the live fuel mix")
    if signal.alerts:
        facts.append("grid alerts: " + "; ".join(signal.alerts))
    if signal.stale:
        facts.append("grid feed is stale: the plan is on last known data")
    return facts


def _fallback(schedule: Schedule, signal: GridSignal) -> str:
    """The solver's facts joined plainly, no LLM."""
    lines = grid_facts(signal) + schedule.explanations
    return " ".join(line.rstrip(".") + "." for line in lines)


_SYSTEM = """You explain a compute schedule to a data-center operator in exactly two plain sentences.
Use only the facts given. Copy every number exactly as written in the facts (you may drop decimals);
never compute, convert or add numbers, and never mention a time or amount the facts do not contain.
Lead with what matters most right now (a grid alert, a stale feed, or which job moved and why)."""


async def explain(schedule: Schedule, signal: GridSignal, llm: LLM) -> Explanation:
    with tracer.start_as_current_span("agent.explain") as span:
        facts = list(schedule.explanations)
        allowed = grid_facts(signal) + facts
        try:
            text = await llm.text(_SYSTEM, "Facts:\n" + "\n".join(f"- {f}" for f in allowed))
        except AgentOffline:
            span.set_attribute("agent.llm_used", False)
            return Explanation(text=_fallback(schedule, signal), facts=facts, llm_used=False)
        bad = ungrounded(text, allowed)
        span.set_attribute("agent.model", llm.name)
        if bad or not text:
            span.set_attribute("agent.rejected_numbers", sorted(bad))
            span.set_attribute("agent.llm_used", False)
            return Explanation(text=_fallback(schedule, signal), facts=facts, llm_used=False)
        span.set_attribute("agent.llm_used", True)
        return Explanation(text=text, facts=facts, llm_used=True)
