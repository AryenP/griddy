"""agent/llm.py: backend selection, the offline path, spans. No network: SDK clients are test fakes."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel

from agent.llm import LLM, AgentOffline, ClaudeLLM, get_llm

SPANS = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(SPANS))
trace.set_tracer_provider(_provider)


class ScriptedLLM(LLM):
    """TEST FAKE: returns canned answers in order, or raises AgentOffline when it runs out."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, str]] = []
        self.name, self.available = "test:scripted", True

    def _next(self, system, user):
        self.calls.append((system, user))
        if not self.answers:
            raise AgentOffline("agent offline")
        return self.answers.pop(0)

    async def text(self, system, user):
        return self._next(system, user)

    async def json(self, system, user, schema):
        answer = self._next(system, user)
        return answer if isinstance(answer, BaseModel) else schema.model_validate(answer)


class _FakeMessages:
    """TEST FAKE for anthropic's `client.messages`."""

    def __init__(self, content, fail=False, parsed=None, stop_reason="end_turn"):
        self.content, self.fail, self.kwargs = content, fail, None
        self.parsed, self.stop_reason = parsed, stop_reason

    def _reply(self, **extra):
        return SimpleNamespace(content=self.content, stop_reason=self.stop_reason,
                               usage=SimpleNamespace(input_tokens=11, output_tokens=7), **extra)

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.fail:
            raise ConnectionError("network down")
        return self._reply()

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.fail:
            raise ConnectionError("network down")
        return self._reply(parsed_output=self.parsed)


class Answer(BaseModel):
    value: int


@pytest.fixture
def no_keys(monkeypatch):
    for var in ("AZURE_AI_PROJECT_ENDPOINT", "AZURE_MODEL_DEPLOYMENT", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        monkeypatch.setenv(var, "")


async def test_offline_without_keys(no_keys):
    llm = get_llm()
    assert not llm.available and llm.name == "offline"
    with pytest.raises(AgentOffline):
        await llm.text("s", "u")
    with pytest.raises(AgentOffline):
        await llm.json("s", "u", Answer)


def test_claude_selected_with_key(no_keys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    llm = get_llm()
    assert llm.available and llm.name == "claude:claude-test"


async def test_claude_text_records_span():
    SPANS.clear()
    fake = _FakeMessages([SimpleNamespace(type="text", text=" agent online ")])
    llm = ClaudeLLM("k", "claude-test", client=SimpleNamespace(messages=fake))
    assert await llm.text("sys", "hi") == "agent online"
    span = SPANS.get_finished_spans()[-1]
    assert span.name == "llm.text"
    assert span.attributes["llm.model"] == "claude-test"
    assert span.attributes["llm.tokens.input"] == 11 and span.attributes["llm.tokens.output"] == 7
    assert span.attributes["llm.latency_ms"] >= 0


async def test_claude_json_uses_structured_outputs():
    fake = _FakeMessages([], parsed=Answer(value=3))
    llm = ClaudeLLM("k", "claude-test", client=SimpleNamespace(messages=fake))
    assert await llm.json("sys", "hi", Answer) == Answer(value=3)
    assert fake.kwargs["output_format"] is Answer
    assert "tool_choice" not in fake.kwargs and "tools" not in fake.kwargs   # forced tool use is a 400 now


async def test_claude_refusal_is_offline():
    fake = _FakeMessages([], parsed=Answer(value=3), stop_reason="refusal")
    llm = ClaudeLLM("k", "claude-test", client=SimpleNamespace(messages=fake))
    with pytest.raises(AgentOffline, match="declined"):
        await llm.json("sys", "hi", Answer)


async def test_claude_failure_is_offline():
    llm = ClaudeLLM("k", "claude-test", client=SimpleNamespace(messages=_FakeMessages([], fail=True)))
    with pytest.raises(AgentOffline):
        await llm.text("sys", "hi")


async def test_claude_bad_json_is_offline():
    fake = _FakeMessages([], parsed={"value": "many"})
    llm = ClaudeLLM("k", "claude-test", client=SimpleNamespace(messages=fake))
    with pytest.raises(AgentOffline):
        await llm.json("sys", "hi", Answer)
