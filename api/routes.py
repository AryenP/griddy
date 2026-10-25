"""HTTP routes (HANDOFF.md API contract). Thin: validate, hand to the runtime, return its result."""
from __future__ import annotations

import asyncio
import hmac
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent import faults, intake
from agent.negotiator import CAP_JOB
from core.config import available_isos, settings
from core.types import CapEvent
from response.engine import kind_for
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


class ResponseIn(BaseModel):
    kind: str = Field("", pattern=r"^(|substation|line|ev_surge|solar_backfeed|demand_surge|clear)$")
    cause: str = Field("", max_length=120)
    line: int = Field(0, ge=0, le=8)
    who: str = "operator"


class CrewIn(BaseModel):
    order: str = Field(max_length=40)
    crew: str = Field(max_length=40)
    status: str = Field(pattern=r"^(assigned|en_route|on_site|repaired)$")
    eta_s: float | None = Field(None, ge=0, le=86400)
    bids: list[dict] | None = Field(None, max_length=10)


class WhatIfIn(BaseModel):
    target: str = Field(pattern=r"^(plant:[A-Za-z]+|hub|city|clear)$")
    share_pct: float = Field(100.0, ge=1, le=100)
    cause: str = Field("", max_length=120)
    who: str = "operator"


class FaultTextIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    target: str | None = Field(None, pattern=r"^(plant:[A-Za-z]+|hub|city)$")
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

    def by(who: str, request: Request, roles: tuple[str, ...] = ("operator",)) -> str:
        """The name typed on the page (self-declared) and where the call came from (not). Operator routes by default."""
        return f"{who} ({access.require(request, roles)})"

    @r.get("/join")
    async def join(t: str = "", next: str = "/operator.html"):
        """A phone joins once (the owner and operator QR codes carry this link): sets the cookie the action
        routes check, then opens the page. A wrong token joins nothing."""
        if not (hmac.compare_digest(t, access.operator_token()) or hmac.compare_digest(t, access.owner_token())):
            raise HTTPException(401, "wrong or missing join token: use the QR code from `make qr`")
        dest = next if next.startswith("/") and not next.startswith("//") and "\\" not in next else "/"   # no "/\\host" (K12 #3)
        resp = RedirectResponse(dest, status_code=303)
        resp.set_cookie(access.COOKIE, t, httponly=True, samesite="strict", max_age=2 * 86400)
        return resp

    @r.websocket("/ws")
    async def ws(sock: WebSocket):
        await rt.broadcaster.serve(sock, rt.snapshot())

    @r.get("/api/runs")
    async def runs():
        """`of_record`: the run is one of the evidence comparisons of record (docs/evidence/claims.yaml), so the Proof
        page picks those by default rather than whatever ran last on this Mac."""
        from agent.reporter import runtime_runs
        return [{**{k: v for k, v in run.items() if k != "path"}, "of_record": run["run_id"] in _of_record()}
                for run in runtime_runs(RUNS)]

    def _of_record() -> set[str]:
        import yaml
        try:
            claims = yaml.safe_load((Path(__file__).resolve().parents[1] / "docs/evidence/claims.yaml").read_text())
        except OSError:
            return set()
        return {c[k] for c in claims.get("comparisons", []) if "of record" in c.get("name", "")
                for k in ("dispatched", "baseline") if c.get(k)}

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
            rt.response.end(why="cleared by the judge")
            return {"cleared": True}
        if body.cause and (rej := intake.guard(body.cause, {"instructions", "secrets"})):
            raise HTTPException(400, f"cause not used: {rej.reason}")
        kind = kind_for(body.target, body.cause)
        if kind in ("ev_surge", "solar_backfeed"):          # a feeder event in the city, not a grid-wide shortfall
            st = rt.response.start(kind, cause=body.cause)
            return {"whatif": False, "label": st["what"], "shortfall_mw": 0, "asked_cut_pct": 0, "response": st}
        try:
            out = rt.whatif.start(body.target, share_pct=body.share_pct, cause=body.cause)
        except KeyError:
            raise HTTPException(404, f"nothing called {body.target!r} to break")
        except ValueError as e:
            raise HTTPException(409, str(e))
        return {**out, "response": rt.response.start(kind, cause=body.cause)}   # Griddy responds on its own

    @r.post("/api/response")
    async def response(body: ResponseIn, request: Request):
        """Start Griddy's automatic emergency response for an incident in the city (response/engine.py): it isolates,
        islands the hospitals, reroutes, sheds what can wait and sends a crew, on its own. Labelled simulated where it is."""
        who = by(body.who, request)
        rt.tl.log("policy", reason=f"incident {body.kind or 'clear'}", who=who)
        if body.kind in ("", "clear"):
            rt.response.end(why=f"cleared by {who}")
            return {"cleared": True}
        if body.cause and (rej := intake.guard(body.cause, {"instructions", "secrets"})):
            raise HTTPException(400, f"cause not used: {rej.reason}")
        try:
            return rt.response.start(body.kind, cause=body.cause, line=body.line)
        except (KeyError, ValueError) as e:
            raise HTTPException(409, str(e))

    @r.get("/api/response")
    async def response_state():
        """The incident Griddy is handling, its steps with what is real and what is simulated, and the crew."""
        return rt.response.last or {"active": False}

    @r.get("/api/response/orders")
    async def response_orders(request: Request):
        """Open work orders, for the crew agents on this Mac (agent/channels/crews.py) only."""
        if not access.is_this_machine(request):
            raise HTTPException(403, "work orders go to the crew agents on this machine only")
        return {"orders": rt.response.open_orders()}

    @r.post("/api/response/crew")
    async def response_crew(body: CrewIn, request: Request):
        """A crew agent's bid result or status (assigned, en route, on site, repaired), from this Mac only."""
        if not access.is_this_machine(request):
            raise HTTPException(403, "crew updates come from the crew agents on this machine only")
        try:
            return rt.response.crew_update(body.order, body.crew, body.status, body.eta_s, body.bids)
        except KeyError as e:
            raise HTTPException(404, f"no open work order or crew {e}")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @r.post("/api/whatif/read")
    async def whatif_read(body: FaultTextIn, request: Request):
        """A judge's own words for a failure, read into a part, a share and a cause (agent/faults.py: a pattern
        first, then the model). Nothing breaks here: the page shows the reading with its real size to confirm."""
        by(body.who, request)
        paid.check(request)
        parts = rt.whatif.parts()
        if not parts:
            raise HTTPException(409, "no grid numbers yet: the fault needs the grid's real supply and demand")
        try:
            got = await faults.read(body.text, body.target, parts, rt.agent.llm)
        except ValueError as e:
            raise HTTPException(422, str(e))
        size = parts[got["target"]] * got["share_pct"] / 100
        return {**got, "size_mw": size, "part_mw": parts[got["target"]]}

    @r.get("/api/cities")
    async def cities():
        """The cities a judge can open from the 3D world (config/cities.yaml) with their REAL hospitals
        (docs/evidence/city/<id>.json, OpenStreetMap, ODbL). The feeders and blocks the page draws are illustrative."""
        import yaml
        root = Path(__file__).resolve().parents[1]
        out = []
        for c in yaml.safe_load((root / "config/cities.yaml").read_text())["cities"]:
            try:
                d = json.loads((root / "docs/evidence/city" / f"{c['id']}.json").read_text())
            except OSError:
                continue
            out.append({**c, "hospitals": d["hospitals"], "source": d["source"], "license": d["license"],
                        "fetched_at": d["fetched_at"]})
        return out

    @r.get("/api/cities/{city_id}/map")
    async def city_map(city_id: str):
        """One real square of the city, 1:1 (docs/evidence/city/<id>-map.json from scripts/fetch_city_map.py):
        buildings with heights, streets, parks, water, mapped power lines and sites, hospitals. OpenStreetMap, ODbL."""
        if not re.fullmatch(r"[a-z-]+", city_id):
            raise HTTPException(404, "no such city")
        p = Path(__file__).resolve().parents[1] / "docs/evidence/city" / f"{city_id}-map.json"
        if not p.is_file():
            raise HTTPException(404, f"no map for {city_id!r}: run scripts/fetch_city_map.py")
        return FileResponse(p, media_type="application/json")

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
        who = by(body.who, request, ("operator", "owner"))            # a job's deadline: its owner, or the operator
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
        """The over-cap request is the operator's; a job's request is its owner's. A phone answers only its own kind
        (HVE Core re-check 20:16); this Mac answers either."""
        access.require(request, ("operator", "owner"))               # a stranger's phone: 401 before any lookup
        req = rt.agent.approvals.get(request_id)
        if req is None:
            raise HTTPException(404, f"no approval request {request_id}")
        who = by(body.who, request, ("operator",) if req.job_id == CAP_JOB else ("owner",))
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
        access.require(request, ("operator", "owner"))
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
