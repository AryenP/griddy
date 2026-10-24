"""HTTP routes (HANDOFF.md API contract). Thin: validate, hand to the runtime, return its result."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.config import available_isos
from core.types import CapEvent
from workloads.base import WL

WEB = Path("web")
RUNS = Path("runs")


def list_runs(root: Path = RUNS) -> list[dict]:
    """Runtime runs (make demo / make baseline) with their mode, from each timeline's first event."""
    out = []
    for tl in sorted(root.glob("*/timeline.jsonl")):
        if tl.parent.is_symlink():
            continue
        try:
            with open(tl) as fh:
                first = json.loads(fh.readline())
        except (OSError, json.JSONDecodeError):
            continue
        d = first.get("data", {})
        if first.get("kind") == "note" and d.get("msg") == "runtime start":
            out.append({"run_id": tl.parent.name, "started": first["t"],
                        "dispatcher_enabled": d.get("dispatcher_enabled"), "machine": d.get("machine")})
    return out


class PolicyIn(BaseModel):
    objective: Literal["cost", "carbon", "balanced"] | None = None
    power_cap_w: float | None = Field(default=None, description="explicit null clears the cap")


class IsoIn(BaseModel):
    iso: str


class DispatcherIn(BaseModel):
    enabled: bool


class JobIn(BaseModel):
    deadline: datetime | None = None


class EventIn(BaseModel):
    start: datetime
    duration_s: int = Field(gt=0)
    target_w: float | None = None
    target_pct: float | None = Field(default=None, gt=0, lt=100)
    reason: str = ""


class ChatIn(BaseModel):
    messages: list[dict]
    max_tokens: int | None = None


class RequestIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    who: str = "operator"


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    who: str


def make_router(rt) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws")
    async def ws(sock: WebSocket):
        await rt.broadcaster.serve(sock, rt.snapshot())

    @r.get("/api/runs")
    async def runs():
        return list_runs()

    @r.get("/api/state")
    async def state():
        return rt.snapshot()

    @r.post("/api/policy")
    async def policy(body: PolicyIn):
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(400, "nothing to change")
        s = await rt.executor.set_policy(**changes)
        return s.model_dump(mode="json") if s else None

    @r.post("/api/iso")
    async def iso(body: IsoIn):
        if body.iso not in available_isos():
            raise HTTPException(400, f"{body.iso} not available: {available_isos()}")
        sig = await rt.switch_iso(body.iso)
        return {"grid": sig.model_dump(mode="json"),
                "schedule": rt.executor.schedule.model_dump(mode="json") if rt.executor.schedule else None}

    @r.post("/api/dispatcher")
    async def dispatcher(body: DispatcherIn):
        rt.executor.set_dispatcher(body.enabled)
        return {"enabled": rt.executor.dispatcher_enabled}

    @r.post("/api/jobs/{job_id}")
    async def job(job_id: str, body: JobIn):
        if job_id not in {j.id for j in rt.executor.jobs()} or job_id == "chat":
            raise HTTPException(404, f"no deferrable job {job_id}")
        s = await rt.executor.set_job(job_id, **body.model_dump(exclude_unset=True))
        return s.model_dump(mode="json") if s else None

    @r.post("/api/event")
    async def event(body: EventIn):
        if (body.target_w is None) == (body.target_pct is None):
            raise HTTPException(400, "give exactly one of target_w or target_pct")
        ev = CapEvent(source="ui", start=body.start, duration_s=body.duration_s, target_w=body.target_w,
                      target_pct=body.target_pct, reason=body.reason, raw=body.model_dump_json())
        try:
            s = await rt.executor.add_event(ev)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return s.model_dump(mode="json") if s else None

    def _dump(m):
        return m.model_dump(mode="json") if m is not None else None

    @r.post("/request")
    async def request(body: RequestIn):
        try:
            result, sched = await rt.agent.request(body.text, body.who)
        except ValueError as e:                      # e.g. % cap before a measured baseline exists
            raise HTTPException(409, str(e))
        return {"intake": _dump(result), "schedule": _dump(sched)}

    @r.post("/openadr/event")
    async def openadr(event: dict):
        try:
            result, sched = await rt.agent.openadr(event, who="openadr")
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"intake": _dump(result), "schedule": _dump(sched)}

    @r.get("/api/approvals")
    async def approvals(owner: str | None = None, status: str | None = "pending"):
        return [_dump(a) for a in rt.agent.pending(owner, status or None)]

    @r.post("/api/approvals/{request_id}/reply")
    async def reply(request_id: str, body: ReplyIn):
        try:
            decision, sched = await rt.agent.reply(request_id, body.text, body.who)
        except KeyError:
            raise HTTPException(404, f"no approval request {request_id}")
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"decision": _dump(decision), "schedule": _dump(sched)}

    @r.get("/api/explain")
    async def explain():
        if rt.agent.explanation is None:
            raise HTTPException(404, "no schedule explained yet")
        return _dump(rt.agent.explanation)

    @r.post("/api/chat")
    async def chat(body: ChatIn):
        url = f"http://127.0.0.1:{WL['chat']['proxy_port']}/chat"
        async with httpx.AsyncClient(timeout=180) as c:
            try:
                resp = await c.post(url, json=body.model_dump(exclude_none=True))
            except httpx.HTTPError as e:
                raise HTTPException(503, f"chat service unavailable: {e!r}")
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, resp.text)
        return resp.json()

    @r.post("/api/chat/stream")
    async def chat_stream(body: ChatIn):
        """Pass the proxy's NDJSON stream through: {"delta"} lines, then {"done", latency_s, ttft_s, ...}."""
        url = f"http://127.0.0.1:{WL['chat']['proxy_port']}/chat/stream"

        async def relay():
            async with httpx.AsyncClient(timeout=180) as c:
                try:
                    async with c.stream("POST", url, json=body.model_dump(exclude_none=True)) as resp:
                        async for line in resp.aiter_lines():
                            if line:
                                yield line + "\n"
                except httpx.HTTPError as e:
                    yield json.dumps({"error": f"chat service unavailable: {e!r}"}) + "\n"
        return StreamingResponse(relay(), media_type="application/x-ndjson")

    @r.get("/chat")
    async def chat_page():
        p = WEB / "chat.html"
        if not p.exists():
            raise HTTPException(404, "web/chat.html not built yet")
        return FileResponse(p)

    return r
