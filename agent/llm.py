"""One LLM interface for the agent layer: Microsoft Agent Framework + Foundry when Azure is configured,
otherwise Claude via the anthropic SDK, otherwise offline. The LLM only reads and writes text; it has no
code path to any knob. Every call is one OpenTelemetry span with model, latency and tokens."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from typing import Any

from dotenv import load_dotenv
from opentelemetry import trace
from pydantic import BaseModel, ValidationError

tracer = trace.get_tracer("brownout.agent")

MAX_TOKENS = 1024
OFFLINE = "agent offline"


class AgentOffline(Exception):
    """No backend configured, or the backend failed. Callers fall back to deterministic output."""


class LLM:
    name: str = "offline"
    available: bool = False

    async def text(self, system: str, user: str) -> str:
        raise AgentOffline(OFFLINE)

    async def json(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        raise AgentOffline(OFFLINE)


def _record(span: trace.Span, model: str, t0: float, tokens_in: int | None, tokens_out: int | None) -> None:
    span.set_attribute("llm.model", model)
    span.set_attribute("llm.latency_ms", round((time.perf_counter() - t0) * 1000, 1))
    if tokens_in is not None:
        span.set_attribute("llm.tokens.input", tokens_in)
    if tokens_out is not None:
        span.set_attribute("llm.tokens.output", tokens_out)


def _parse_json(raw: str, schema: type[BaseModel]) -> BaseModel:
    """Parse model text as `schema`, tolerating a ```json fence around it."""
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return schema.model_validate_json(m.group(0) if m else raw)
    except ValidationError as e:
        raise AgentOffline(f"model output did not match {schema.__name__}: {e.error_count()} error(s)") from e


class ClaudeLLM(LLM):
    """Claude through the anthropic SDK. Structured output via one forced tool call."""

    def __init__(self, api_key: str, model: str, client: Any | None = None):
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=api_key)
        self._client = client
        self.model = model
        self.name = f"claude:{model}"
        self.available = True

    async def _create(self, kind: str, **kwargs: Any) -> Any:
        with tracer.start_as_current_span(f"llm.{kind}") as span:
            t0 = time.perf_counter()
            try:
                msg = await self._client.messages.create(model=self.model, max_tokens=MAX_TOKENS, **kwargs)
            except Exception as e:  # network, auth, rate limit: the agent is offline for this call
                span.record_exception(e)
                _record(span, self.model, t0, None, None)
                raise AgentOffline(f"{OFFLINE}: {type(e).__name__}") from e
            usage = getattr(msg, "usage", None)
            _record(span, self.model, t0, getattr(usage, "input_tokens", None),
                    getattr(usage, "output_tokens", None))
            return msg

    async def text(self, system: str, user: str) -> str:
        msg = await self._create("text", system=system, messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()

    async def json(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        tool = {"name": schema.__name__, "description": schema.__doc__ or schema.__name__,
                "input_schema": schema.model_json_schema()}
        msg = await self._create("json", system=system, messages=[{"role": "user", "content": user}],
                                 tools=[tool], tool_choice={"type": "tool", "name": schema.__name__})
        for b in msg.content:
            if getattr(b, "type", "") == "tool_use":
                try:
                    return schema.model_validate(b.input)
                except ValidationError as e:
                    raise AgentOffline(f"model output did not match {schema.__name__}") from e
        raise AgentOffline(f"model returned no {schema.__name__}")


class FoundryLLM(LLM):
    """Microsoft Agent Framework `Agent` over `FoundryChatClient` (Azure AI Foundry deployment)."""

    def __init__(self, endpoint: str, deployment: str, client: Any | None = None):
        if client is None:
            from agent_framework.foundry import FoundryChatClient
            from azure.identity.aio import DefaultAzureCredential

            client = FoundryChatClient(project_endpoint=endpoint, model=deployment,
                                       credential=DefaultAzureCredential())
        self._client = client
        self.model = deployment
        self.name = f"foundry:{deployment}"
        self.available = True

    async def _run(self, kind: str, system: str, user: str, options: dict | None = None) -> Any:
        from agent_framework import Agent

        with tracer.start_as_current_span(f"llm.{kind}") as span:
            t0 = time.perf_counter()
            try:
                resp = await Agent(self._client, instructions=system).run(user, options=options)
            except Exception as e:
                span.record_exception(e)
                _record(span, self.model, t0, None, None)
                raise AgentOffline(f"{OFFLINE}: {type(e).__name__}") from e
            usage = getattr(resp, "usage_details", None) or {}
            _record(span, self.model, t0, usage.get("input_token_count"), usage.get("output_token_count"))
            return resp

    async def text(self, system: str, user: str) -> str:
        return (await self._run("text", system, user)).text.strip()

    async def json(self, system: str, user: str, schema: type[BaseModel]) -> BaseModel:
        resp = await self._run("json", system, user, {"response_format": schema})
        if isinstance(resp.value, schema):
            return resp.value
        return _parse_json(resp.text, schema)


def get_llm() -> LLM:
    """Agent Framework + Foundry when AZURE_AI_PROJECT_ENDPOINT is set, else Claude, else offline."""
    load_dotenv()
    endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").strip()
    deployment = os.getenv("AZURE_MODEL_DEPLOYMENT", "").strip()
    if endpoint and deployment:
        try:
            return FoundryLLM(endpoint, deployment)
        except ImportError:
            pass  # azure extras not installed: fall through to Claude
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = os.getenv("ANTHROPIC_MODEL", "").strip()
    if key and model:
        return ClaudeLLM(key, model)
    return LLM()


def _main() -> None:
    """`python -m agent.llm "question"`: one call with spans printed to the console."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?", default="Say 'agent online' and nothing else.")
    args = ap.parse_args()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    llm = get_llm()
    print(json.dumps({"name": llm.name, "available": llm.available}))
    try:
        print(asyncio.run(llm.text("You are a terse assistant.", args.prompt)))
    except AgentOffline as e:
        print(f"offline: {e}")


if __name__ == "__main__":
    _main()
