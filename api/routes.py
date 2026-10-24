"""HTTP routes (HANDOFF.md API contract). Thin: validate, hand to the runtime, return its result."""
from __future__ import annotations

import hmac
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.config import available_isos, settings
from core.types import CapEvent
from workloads.base import WL

WEB = Path("web")
RUNS = Path("runs")


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


class NeighbourhoodIn(BaseModel):
    action: Literal["start", "stop"]


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


def make_router(rt) -> APIRouter:
    r = APIRouter()

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

    @r.post("/api/neighbourhood")
    async def neighbourhood(body: NeighbourhoodIn):
        """Start or stop the SIMULATED neighbourhood's time-lapse (config/neighbourhood.yaml scenario)."""
        if not rt.neighbourhood.enabled:
            raise HTTPException(404, "no neighbourhood configured (config/neighbourhood.yaml)")
        return rt.neighbourhood.start() if body.action == "start" else rt.neighbourhood.stop()

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

    @r.post("/api/ask")
    async def ask(body: AskIn):
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
