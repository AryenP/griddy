"""HTTP routes (HANDOFF.md API contract). Thin: validate, hand to the runtime, return its result."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.config import available_isos
from core.types import CapEvent
from workloads.base import WL

WEB = Path("web")


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


def make_router(rt) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws")
    async def ws(sock: WebSocket):
        await rt.broadcaster.serve(sock, rt.snapshot())

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

    @r.get("/chat")
    async def chat_page():
        p = WEB / "chat.html"
        if not p.exists():
            raise HTTPException(404, "web/chat.html not built yet")
        return FileResponse(p)

    return r
