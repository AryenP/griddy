"""HTTP routes (HANDOFF.md API contract). Thin: validate, hand to the runtime, return its result."""
from __future__ import annotations

import asyncio
import hmac
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.config import available_isos, settings
from core.types import CapEvent
from workloads.base import WL

from . import access

WEB = Path("web")
RUNS = Path("runs")


class PolicyIn(BaseModel):
    objective: Literal["cost", "carbon", "balanced"] | None = None
    power_cap_w: float | None = Field(default=None, description="explicit null clears the cap")
    who: str = "operator"


class IsoIn(BaseModel):
    iso: str
    who: str = "operator"


class DispatcherIn(BaseModel):
    enabled: bool
    who: str = "operator"


class JobIn(BaseModel):
    deadline: datetime | None = None
    who: str = "operator"


class EventIn(BaseModel):
    start: datetime
    duration_s: int = Field(gt=0)
    target_w: float | None = None
    target_pct: float | None = Field(default=None, gt=0, lt=100)
    reason: str = ""


class SiteBeat(BaseModel):
    """A laptop's heartbeat (fleet/agent.py): its battery reading and its job's progress."""
    t: float | None = None
    watts: float | None = Field(default=None, ge=0)
    meter_t: float | None = None
    meter_changed_t: float | None = None
    meter_note: str = ""
    plugged: bool | None = None
    running: bool | None = None
    done_mb: float | None = Field(default=None, ge=0)
    rate_mb_s: float | None = Field(default=None, ge=0)
    machine: str = ""


class SiteCalibration(BaseModel):
    """A laptop's own calibration (fleet/agent.py --calibrate), measured by its battery."""
    idle_w: float = Field(ge=0)
    delta_w: float = Field(ge=0)
    rate_mb_s: float = Field(gt=0)
    samples: list[int] = Field(default_factory=list)
    window_s: float = Field(gt=0)
    threads: int = Field(ge=1)
    measured_at: float
    machine: str
    meter: str


class WhatIfIn(BaseModel):
    target: str = Field(pattern=r"^(plant:[A-Za-z]+|hub|city|clear)$")
    who: str = "operator"


class ReplayIn(BaseModel):
    action: Literal["start", "stop"]
    event: str | None = None
    who: str = "operator"


class ChatIn(BaseModel):
    messages: list[dict]
    max_tokens: int | None = None


class RequestIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    who: str = "operator"


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    who: str
    owner: str | None = Field(default=None, description="the owner this console acts as; else `who`")


def make_router(rt) -> APIRouter:
    r = APIRouter()
    paid = access.RateLimit(n=10, per_s=60)       # /request and /api/ask each cost a model call

    def by(who: str, request: Request) -> str:
        """The name typed on the page (self-declared) and where the call came from (not)."""
        return f"{who} ({access.require(request)})"

    @r.get("/join")
    async def join(t: str = "", next: str = "/operator.html"):
        """A phone joins once (the owner and operator QR codes carry this link): sets the cookie the action
        routes check, then opens the page. A wrong token joins nothing."""
        if not hmac.compare_digest(t, access.operator_token()):
            raise HTTPException(401, "wrong or missing join token: use the QR code from `make qr`")
        dest = next if next.startswith("/") and not next.startswith("//") else "/"
        resp = RedirectResponse(dest, status_code=303)
        resp.set_cookie(access.COOKIE, t, httponly=True, samesite="strict", max_age=2 * 86400)
        return resp

    @r.websocket("/ws")
    async def ws(sock: WebSocket):
        await rt.broadcaster.serve(sock, rt.snapshot())

    @r.get("/api/runs")
    async def runs():
        from agent.reporter import runtime_runs
        return [{k: v for k, v in run.items() if k != "path"} for run in runtime_runs(RUNS)]

    @r.get("/api/runs/{run_id}/series")
    async def run_series(run_id: str):
        from agent.reporter import run_path, run_series
        try:
            return run_series(run_path(run_id, RUNS))
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))

    def _fleet_auth(token: str | None) -> None:
        """Laptops' watts count against the cap: with FLEET_TOKEN set, only a laptop that knows it may post
        (Krish K1 #4: the venue network has judges' phones on it)."""
        want = settings.fleet_token
        if want and not hmac.compare_digest(token or "", want):
            raise HTTPException(401, "missing or wrong X-Brownout-Fleet-Token")

    @r.post("/api/sites/{site_id}/beat")
    async def site_beat(site_id: str, body: SiteBeat, x_brownout_fleet_token: str | None = Header(default=None)):
        _fleet_auth(x_brownout_fleet_token)
        if site_id not in rt.fleet.sites:
            raise HTTPException(404, f"{site_id!r} is not a site in config/fleet.yaml")
        return rt.fleet.beat(site_id, body.model_dump())

    @r.post("/api/sites/{site_id}/calibration")
    async def site_calibration(site_id: str, body: SiteCalibration,
                               x_brownout_fleet_token: str | None = Header(default=None)):
        _fleet_auth(x_brownout_fleet_token)
        if site_id not in rt.fleet.sites:
            raise HTTPException(404, f"{site_id!r} is not a site in config/fleet.yaml")
        return rt.fleet.calibrate(site_id, body.model_dump())

    @r.post("/api/whatif")
    async def whatif(body: WhatIfIn, request: Request):
        """A judge breaks a part of the grid: real-sized (replay/whatif.py), labelled what-if; `clear` ends it."""
        who = by(body.who, request)
        rt.tl.log("policy", reason=f"what-if {body.target}", who=who)
        if body.target == "clear":
            rt.whatif.end()
            return {"cleared": True}
        try:
            return rt.whatif.start(body.target)
        except KeyError:
            raise HTTPException(404, f"nothing called {body.target!r} to break")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @r.get("/api/replay/events")
    async def replay_events():
        """The real grid emergencies a judge can replay, with their EIA-930 hours, cited alerts and impact."""
        return rt.replay.catalog()

    @r.post("/api/replay")
    async def replay(body: ReplayIn, request: Request):
        """Start (with `event`) or stop a replay of a real grid emergency through the live software."""
        who = by(body.who, request)
        rt.tl.log("policy", reason=f"replay {body.action}", event=body.event, who=who)
        if body.action == "stop":
            return rt.replay.stop()
        if body.event not in rt.replay.events:
            raise HTTPException(404, f"no event {body.event!r}: {sorted(rt.replay.events)}")
        await asyncio.to_thread(rt.replay.prepare, body.event)    # the event's hours, live from api.eia.gov
        return rt.replay.start(body.event)

    @r.get("/api/state")
    async def state():
        return rt.snapshot()

    @r.post("/api/policy")
    async def policy(body: PolicyIn, request: Request):
        who = by(body.who, request)
        changes = body.model_dump(exclude_unset=True, exclude={"who"})
        if not changes:
            raise HTTPException(400, "nothing to change")
        s = await rt.executor.set_policy(who=who, **changes)
        return s.model_dump(mode="json") if s else None

    @r.post("/api/iso")
    async def iso(body: IsoIn, request: Request):
        who = by(body.who, request)
        if body.iso not in available_isos():
            raise HTTPException(400, f"{body.iso} not available: {available_isos()}")
        sig = await rt.switch_iso(body.iso, who=who)
        return {"grid": sig.model_dump(mode="json"),
                "schedule": rt.executor.schedule.model_dump(mode="json") if rt.executor.schedule else None}

    @r.post("/api/dispatcher")
    async def dispatcher(body: DispatcherIn, request: Request):
        rt.executor.set_dispatcher(body.enabled, who=by(body.who, request))
        return {"enabled": rt.executor.dispatcher_enabled}

    @r.post("/api/jobs/{job_id}")
    async def job(job_id: str, body: JobIn, request: Request):
        who = by(body.who, request)
        if job_id not in {j.id for j in rt.executor.jobs()} or job_id == "chat":
            raise HTTPException(404, f"no deferrable job {job_id}")
        s = await rt.executor.set_job(job_id, who=who, **body.model_dump(exclude_unset=True, exclude={"who"}))
        return s.model_dump(mode="json") if s else None

    @r.post("/api/event")
    async def event(body: EventIn, request: Request):
        who = access.require(request)
        if (body.target_w is None) == (body.target_pct is None):
            raise HTTPException(400, "give exactly one of target_w or target_pct")
        ev = CapEvent(source="ui", start=body.start, duration_s=body.duration_s, target_w=body.target_w,
                      target_pct=body.target_pct, reason=body.reason or f"set from {who}", raw=body.model_dump_json())
        try:
            s = await rt.executor.add_event(ev)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return s.model_dump(mode="json") if s else None

    def _dump(m):
        return m.model_dump(mode="json") if m is not None else None

    @r.post("/request")
    async def request(body: RequestIn, request: Request):
        who = by(body.who, request)
        paid.check(request)
        try:
            result, sched = await rt.agent.request(body.text, who)
        except ValueError as e:                      # e.g. % cap before a measured baseline exists
            raise HTTPException(409, str(e))
        return {"intake": _dump(result), "schedule": _dump(sched)}

    @r.post("/openadr/event")
    async def openadr(event: dict, request: Request):
        access.require(request)
        try:
            result, sched = await rt.agent.openadr(event, who="openadr")
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"intake": _dump(result), "schedule": _dump(sched)}

    @r.get("/api/approvals")
    async def approvals(owner: str | None = None, status: str | None = "pending"):
        return [_dump(a) for a in rt.agent.pending(owner, status or None)]

    @r.post("/api/approvals/{request_id}/reply")
    async def reply(request_id: str, body: ReplyIn, request: Request):
        who = by(body.who, request)
        try:
            decision, sched = await rt.agent.reply(request_id, body.text, who, acting_as=body.owner or body.who)
        except KeyError:
            raise HTTPException(404, f"no approval request {request_id}")
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {"decision": _dump(decision), "schedule": _dump(sched)}

    @r.post("/api/ask")
    async def ask(body: AskIn, request: Request):
        access.require(request)
        paid.check(request)
        return _dump(await rt.agent.ask(body.question))

    @r.get("/api/explain")
    async def explain():
        if rt.agent.explanation is None:
            raise HTTPException(404, "no schedule explained yet")
        return _dump(rt.agent.explanation)

    @r.get("/api/report")
    async def report(run: str = "latest"):
        from agent.reporter import build_report, run_path
        try:
            return _dump(build_report(run_path(run, RUNS)))
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))

    @r.get("/api/compare")
    async def compare(dispatched: str | None = None, baseline: str | None = None,
                      baseline_policy: Literal["baseline", "pause_all"] = "baseline"):
        """Run ids, or the newest dispatched run vs the newest run of `baseline_policy`."""
        from agent.reporter import compare_runs, newest, run_path
        try:
            d = run_path(dispatched, RUNS) if dispatched else newest(True, RUNS)
            b = run_path(baseline, RUNS) if baseline else newest(False, RUNS, baseline_policy)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        return _dump(compare_runs(d, b))

    @r.get("/api/trace")
    async def trace(n: int = 50):
        import telemetry
        return telemetry.recent_spans(max(1, min(n, 500)))

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
