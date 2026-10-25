"""Shared by Griddy's three Fetch.ai agents (team/2-anuraag.md FA1): the messages they exchange, the loopback-only
HTTP client with an exact allowlist per agent, the address allowlists and a per-sender rate limit.

The flow is the shape of a real demand-response deal. Grid Desk (the utility side, the only agent a judge talks to
in ASI:One) sends a CurtailmentRequest to Facility (this Mac). Facility stages it in Griddy's own intake and answers
with an Offer; nothing applies until the operator approves on the operator page, and Facility reports the Outcome.
Grid Desk then asks Verifier, which reads the measured watts from the run's timeline on disk, for a Verdict.

Like agent/channels/fetch_agent.py, nothing here imports uagents at the top: uagents pins protobuf < 6 and the
runtime's OR-Tools needs 6, so the agents run in their own environment (`make fetch-three`) and the runtime's tests
import this file without it. `models(Base)` builds the message classes on whichever base the caller passes:
uagents' Model in the agents, pydantic's BaseModel in tests. The class names and fields are the same either way."""
from __future__ import annotations

import ipaddress
import os
import re
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"grid_desk": "Griddy Grid Desk", "facility": "Griddy Facility", "verifier": "Griddy Verifier"}
PROTOCOL = ("griddy-curtailment", "0.1.0")
WHO = "Grid Desk (Fetch.ai)"            # how a staged request is attributed in the runtime's timeline


def models(Base) -> SimpleNamespace:
    """The five messages, built on `Base` (uagents.Model or pydantic.BaseModel). Times are ISO-8601 strings or
    epoch seconds as the runtime gave them; watts are measured or the intake's own target, never typed here."""

    class CurtailmentRequest(Base):
        id: str
        target_pct: float | None = None     # a cut below the facility's measured baseline
        target_w: float | None = None       # or a cap in watts
        start: str | None = None            # None: as soon as the operator approves
        duration_s: int
        reason: str = ""
        requested_by: str = ""

    class Offer(Base):
        request_id: str
        status: str                         # offered | clarify | rejected | down | error
        readback: str = ""                  # the intake's own words
        target_w: float | None = None
        actions: list[str] = []             # what the solver would pause, slow or move
        needs_approval: bool = True
        approval_id: str | None = None
        message: str = ""                   # the question back, the reason, or what went wrong

    class Outcome(Base):
        request_id: str
        accepted: bool
        status: str                         # approved | refused | expired | countered | down | timeout
        words: str = ""                     # the operator's own words, when the runtime gives them
        who: str = ""
        cap_id: str | None = None
        cap_start: str | None = None
        target_w: float | None = None
        duration_s: int | None = None
        run_id: str | None = None

    class VerifyRequest(Base):
        request_id: str
        run_id: str | None = None
        cap_id: str | None = None
        target_w: float | None = None

    class Verdict(Base):
        request_id: str
        measured: bool
        run_id: str | None = None
        file: str | None = None
        cap_id: str | None = None
        target_w: float | None = None
        window_start: float | None = None
        window_end: float | None = None
        baseline_w: float | None = None     # mean measured W in the 60 s before the cap
        mean_w: float | None = None         # mean measured W in the window
        time_to_compliance_s: float | None = None
        under_cap_pct: float | None = None
        samples: int = 0
        note: str = ""

    return SimpleNamespace(CurtailmentRequest=CurtailmentRequest, Offer=Offer, Outcome=Outcome,
                           VerifyRequest=VerifyRequest, Verdict=Verdict)


# ---------------------------------------------------------------------------------------------- the runtime, on loopback
class NotAllowed(Exception):
    """A call outside this agent's allowlist. Raised before any request is built: it never reaches the runtime."""


class RuntimeDown(Exception):
    """The runtime did not answer, or answered with an error: the reply says so and quotes no number."""


class Refused(Exception):
    """The runtime answered 4xx (a 429 is its rate limit)."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


def loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Loopback:
    """The runtime's HTTP API on this Mac, limited to `allowed` (method, path) pairs. `transport` lets tests answer
    in place of the runtime."""

    def __init__(self, base_url: str, allowed: frozenset[tuple[str, str]], transport: httpx.BaseTransport | None = None,
                 timeout_s: float = 30.0):
        host = urlsplit(base_url).hostname or ""
        if not loopback(host):
            raise ValueError(f"the runtime must be on this machine (loopback), not {host!r}")
        self.base_url, self.allowed = base_url.rstrip("/"), allowed
        self._http = httpx.Client(base_url=self.base_url, transport=transport, timeout=timeout_s,
                                  follow_redirects=False)

    def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> Any:
        if (method, path) not in self.allowed:
            raise NotAllowed(f"{method} {path} is not one of this agent's calls")
        try:
            r = self._http.request(method, path, json=body, params=params)
        except httpx.HTTPError as e:
            raise RuntimeDown(e.__class__.__name__) from e
        if 400 <= r.status_code < 500:
            try:
                detail = str(r.json().get("detail", ""))
            except (ValueError, AttributeError):
                detail = r.text[:200]
            raise Refused(r.status_code, detail)
        if r.status_code != 200:                      # 5xx, or a redirect (never followed)
            raise RuntimeDown(f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise RuntimeDown("not JSON") from e


def runtime_url() -> str:
    return f"http://127.0.0.1:{os.getenv('PORT', '8080')}"


# ---------------------------------------------------------------------------------------------- who may talk to whom
_ADDRESS = re.compile(r"^agent1[02-9ac-hj-np-z]{20,}$")


def address_of(role: str, env: dict | None = None) -> str | None:
    """The agent address for `role` from .env: FETCH_<ROLE>_ADDRESS, else derived from FETCH_<ROLE>_SEED (all three run
    on this Mac with their seeds in its .env). None when neither is set."""
    env = os.environ if env is None else env
    a = (env.get(f"FETCH_{role.upper()}_ADDRESS") or "").strip()
    if a:
        if not _ADDRESS.match(a):
            raise ValueError(f"FETCH_{role.upper()}_ADDRESS is not an agent address")
        return a
    seed = (env.get(f"FETCH_{role.upper()}_SEED") or "").strip()
    if not seed:
        return None
    from uagents.crypto import Identity            # the agents' own environment only
    return Identity.from_seed(seed, 0).address


def allowed(sender: str, addresses: set[str | None]) -> bool:
    """Only an allowlisted address is answered; anything else is dropped (and logged by the caller)."""
    return bool(sender) and sender in {a for a in addresses if a}


def register(agent, seed: str, key: str, name: str, description: str, readme: str = "",
             starters: list[str] | None = None) -> str | None:
    """Create the agent's Agentverse mailbox and profile with the API key (as agent/channels/fetch_agent.py does).
    Returns None, or why it failed (never the key)."""
    import requests
    from uagents_core.config import AgentverseConfig
    from uagents_core.utils.registration import (
        AgentverseRegistrationRequest,
        AgentverseRequestError,
        RegistrationRequestCredentials,
        register_agent,
    )
    av = AgentverseConfig()
    try:
        register_agent(AgentverseRegistrationRequest(name=name, endpoint=av.mailbox_endpoint, type="mailbox",
                                                     protocols=list(agent.protocols), description=description,
                                                     readme=readme, starter_prompts=starters or [],
                                                     track_interactions=False),
                       av, RegistrationRequestCredentials(agentverse_api_key=key, agent_seed_phrase=seed))
    except AgentverseRequestError as e:
        return str(e) or e.from_exc.__class__.__name__
    except requests.RequestException as e:
        return f"could not reach Agentverse ({e.__class__.__name__})"
    return None


def connect_on_startup(agent, seed: str, key: str, name: str, description: str, readme: str = "",
                       starters: list[str] | None = None) -> None:
    """Register on Agentverse when the agent starts, if the human has put AGENTVERSE_API_KEY in .env."""
    if not key:
        print(f"{name}: AGENTVERSE_API_KEY is empty in .env, so it has no mailbox and cannot be reached "
              "(docs/judging/fetch-three-agents.md, setup)")
        return
    import asyncio

    @agent.on_event("startup")
    async def connect(ctx):
        why = await asyncio.to_thread(register, agent, seed, key, name, description, readme, starters)
        if why:
            ctx.logger.error(f"Agentverse registration failed: {why}")
        else:
            ctx.logger.info(f"{name} registered on Agentverse with a mailbox")


class RateLimit:
    """At most `n` messages per `per_s` seconds per sender; the rest get one short answer and nothing else."""

    def __init__(self, n: int = 6, per_s: float = 60.0):
        self.n, self.per_s, self.seen = n, per_s, {}

    def allow(self, sender: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        q = self.seen.setdefault(sender, deque())
        while q and q[0] <= now - self.per_s:
            q.popleft()
        if len(q) >= self.n:
            return False
        q.append(now)
        return True
