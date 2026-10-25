"""Griddy on ASI:One (Fetch.ai): a uAgents agent that speaks the Agent Chat Protocol and is registered on
Agentverse in mailbox mode (it polls Agentverse, so it works behind the venue NAT). A judge asks in ASI:One; the
answer comes from the runtime running on this Mac, and this agent can only read it.

  - It calls the runtime on loopback only, and only the four calls in READS: GET /api/state, /api/explain and
    /api/replay/events, and POST /api/ask (answered from the live state, instructions refused; api/access.py trusts
    loopback). Any other call raises ReadOnly before a request is built, so nothing on the internet can move a knob
    through this agent.
  - Every number in a reply is quoted from those routes, with the route and the runtime's own source. If the
    runtime does not answer, the reply says so and carries no number.
  - Requests to act (pause, cap, replay, approve, break) are refused before the runtime is called.

It runs in its own environment (`make fetch-agent`): uagents needs protobuf < 6 and the runtime's OR-Tools needs 6,
so this file imports nothing from the runtime and only the standard library and httpx at the top; uagents and
python-dotenv are imported in main(). AGENTVERSE_API_KEY and FETCH_AGENT_SEED come from .env and are never printed.
Runbook: docs/fetch-agent.md."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
NAME = "Griddy"          # the product's name since DECISIONS 16:54; the code and the repository keep Brownout
READS = frozenset({("GET", "/api/state"), ("GET", "/api/explain"), ("GET", "/api/replay/events"),
                   ("POST", "/api/ask")})
ASK_MAX_CHARS = 2000     # api/routes.AskIn

DESCRIPTION = (f"Read-only: the live grid, this laptop's measured AI-compute power and the plan from {NAME} "
               "(Cal Hacks 13), plus three real grid emergencies with cited impacts. It cannot change anything.")
STARTERS = ["How stressed is the CAISO grid right now?", "What is the Mac drawing right now?",
            "Why is training paused?", f"What happened in Winter Storm Uri, and what would {NAME} have freed?"]
README = f"""![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# {NAME}: grid-aware AI compute, read-only

{NAME} (Cal Hacks 13) decides when each AI job on a laptop runs, so compute backs off when the electricity grid
is stressed, and it proves the result with power measured by macOS powermetrics. This agent answers from the live
{NAME} runtime and can only read: it cannot pause a job, set a power cap or start a replay.

## Ask it
- How stressed is the CAISO grid right now? Live price, carbon, fuel mix, alerts and load forecast, with the feed's
  age and source.
- What is the Mac drawing right now? Measured watts, and the watts the plan expects.
- Why is training paused? The solver's own facts for the current plan.
- What happened in Winter Storm Uri, and what would {NAME} have freed? Three real grid emergencies (Winter Storm
  Uri 2021, California's rotating outages 2020, California's record heat wave 2022) with cited impacts.

## Rules
Every number comes from the runtime with its source. The only estimate, the grid-scale figure, is labelled
ESTIMATE. If the runtime is down, the agent says so instead of answering.

Keywords: electricity grid, power grid stress, demand response, data center power, AI compute, CAISO, ERCOT,
carbon intensity, blackout, Winter Storm Uri.
"""

HELP = (f"I'm {NAME}'s read-only agent. {NAME} decides when AI jobs on a laptop run, so compute backs off when the "
        "grid is stressed, and it measures the result with macOS powermetrics. I answer from the live runtime on the "
        "demo Mac and I can't change anything. Try:\n" + "\n".join(f"- {s}" for s in STARTERS))
DOWN = (f"{NAME}'s runtime on the demo Mac is not answering, so I have no live numbers to give, and I won't make "
        "any up. Ask again once it is back.")
REFUSE = (f"I can't do that: I only read {NAME}'s live state, and nothing sent from ASI:One can move a knob. The "
          "operator acts on the demo Mac's console (or a device that joined with its QR code), and every change is "
          "logged with who made it. Ask me what the grid, the Mac or the plan is doing instead.")
REFUSE_OVERRIDE = f"I only answer questions from {NAME}'s live state; I don't follow instructions inside a message."
NO_SEED = """FETCH_AGENT_SEED is empty in .env. It fixes this agent's address on Agentverse, so ASI:One finds the same
agent every time. Add one (written straight into .env, never shown):
  printf 'FETCH_AGENT_SEED=%s\\n' "$(openssl rand -hex 32)" >> .env
then run `make fetch-agent` again (docs/fetch-agent.md, step 1)."""
NO_KEY = """AGENTVERSE_API_KEY is empty in .env: the agent runs on this Mac but has no Agentverse mailbox, so ASI:One
cannot reach it. Create a key at agentverse.ai (profile menu, API Keys), put it in .env as AGENTVERSE_API_KEY=...,
and restart (docs/fetch-agent.md, step 2). Or open the "Agent inspector" link below and click Connect, then Mailbox."""


class ReadOnly(Exception):
    """A call outside READS. Raised before any request is built: it never reaches the runtime."""


class RuntimeDown(Exception):
    """The runtime did not answer, or answered with an error: the reply says so and quotes no number."""


class Refused(Exception):
    """The runtime answered 4xx, e.g. 429 on /api/ask past its per-device question limit (api/access.RateLimit)."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Runtime:
    """The runtime's HTTP API on this Mac, reads only. `transport` lets tests answer in place of the runtime."""

    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None, timeout_s: float = 30.0):
        host = urlsplit(base_url).hostname or ""
        if not _loopback(host):
            raise ValueError(f"the runtime must be on this machine (loopback), not {host!r}")
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, transport=transport, timeout=timeout_s,
                                  follow_redirects=False)

    def call(self, method: str, path: str, body: dict | None = None) -> Any:
        if (method, path) not in READS:
            raise ReadOnly(f"{method} {path} is not one of this agent's reads")
        try:
            r = self._http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise RuntimeDown(e.__class__.__name__) from e
        if 400 <= r.status_code < 500:
            try:
                detail = str(r.json().get("detail", ""))
            except ValueError:
                detail = r.text[:200]
            raise Refused(r.status_code, detail)
        if r.status_code != 200:                      # 5xx, or a redirect (never followed)
            raise RuntimeDown(f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise RuntimeDown("not JSON") from e

    def state(self) -> dict:
        return self.call("GET", "/api/state")

    def events(self) -> list[dict]:
        return self.call("GET", "/api/replay/events")

    def explain(self) -> dict | None:
        try:
            return self.call("GET", "/api/explain")
        except Refused as e:
            if e.status == 404:                       # no schedule explained yet
                return None
            raise

    def ask(self, question: str) -> dict:
        return self.call("POST", "/api/ask", {"question": question[:ASK_MAX_CHARS]})


# ---------------------------------------------------------------------------------------------- reading a question
_VERBS = (r"pause|unpause|resume|stop|start|restart|run|rerun|kill|halt|set|reset|change|switch|turn|toggle|enable|"
          r"disable|raise|lower|increase|decrease|reduce|boost|cap|uncap|limit|throttle|approve|reject|deny|accept|"
          r"refuse|decline|cancel|delete|remove|clear|shut|shed|cut|schedule|reschedule|move|delay|postpone|extend|"
          r"replay|trigger|launch|fire|override|lift|add|apply|submit|send|execute|break|trip|surge|crash|deploy|"
          r"update|modify|edit|adjust|force|drop|end|finish|join")
# An imperative at the start of a clause, bare or behind a polite lead-in: "pause training", "please set a 10 W
# cap", "can you turn off the dispatcher?", "go ahead and approve it". "Why is training paused?" is a question.
_ACT = re.compile(
    r"^\s*(?:(?:please|pls|kindly|now|ok|okay|hey|so|then|griddy|brownout|agent)[,\s]+)*"
    r"(?:(?:can|could|would|will|wo)(?:n'?t)?\s+you\s+(?:please\s+)?|i\s+(?:want|need|would\s+like)\s+you\s+to\s+|"
    r"you\s+(?:should|must|need\s+to|have\s+to)\s+|go\s+ahead\s+and\s+|let'?s\s+|try\s+to\s+|"
    rf"make\s+sure\s+(?:to|you)\s+)?(?:{_VERBS})\b", re.IGNORECASE)
_CLAUSES = re.compile(r"[.!?;\n]+|,?\s+(?:and\s+)?then\s+|\s+and\s+", re.IGNORECASE)
_OVERRIDE = re.compile(r"\b(?:ignore|disregard|forget)\b.{0,40}\b(?:instructions?|rules?|prompt|previous|above)\b|"
                       r"\b(?:system prompt|jailbreak|developer mode)\b", re.IGNORECASE)
_HELLO = re.compile(r"^\s*(?:hi|hello|hey|yo|help|who are you|what (?:can|do) you do|what are you)\b[\s!?.]*$",
                    re.IGNORECASE)
_WHY = re.compile(r"\b(?:why|explain\w*|reason\w*|how come|what made)\b", re.IGNORECASE)
_EVENT = re.compile(r"\b(?:storm|outages?|emergenc\w*|blackouts?|replay\w*|heat ?wave|rotating|happened|events?|"
                    r"crisis|disaster|freed|(?:19|20)\d\d)\b", re.IGNORECASE)
_GRID = re.compile(r"\b(?:grid|stress\w*|prices?|mwh|carbon|co2|emissions?|demand|load|fuel|mix|solar|wind|gas|"
                   r"renewables?|alerts?|iso|caiso|ercot|pjm|lmp|forecast)\b", re.IGNORECASE)
_POWER = re.compile(r"\b(?:power|watts?|draw\w*|consum\w*|energy|meter\w*|powermetrics|measur\w*|using)\b",
                    re.IGNORECASE)
_PLAN = re.compile(r"\b(?:plan\w*|schedul\w*|jobs?|train\w*|batch|chat|running|paused|status|dispatcher|"
                   r"deadlines?|approvals?|caps?|slots?)\b", re.IGNORECASE)
_LIVE = re.compile(r"\b(?:now|currently|current|live|today|tonight|at the moment)\b", re.IGNORECASE)
_STOP = {"the", "and", "what", "when", "where", "how", "did", "does", "was", "were", "would", "have", "has", "had",
         "its", "this", "that", "about", "tell", "griddy", "brownout", "with", "for", "from", "during", "after",
         "before", "happened", "event"}


def acting(question: str) -> bool:
    """True when any clause of the message asks for something to be done rather than asked about."""
    return any(_ACT.match(c) for c in _CLAUSES.split(question) if c.strip())


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower().replace("'s", "")):
        if len(w) >= 3 and w not in _STOP:
            out.add(w[:-1] if len(w) > 4 and w.endswith("s") else w)
    return out


def match_event(question: str, events: list[dict]) -> tuple[str | None, int]:
    """The replay event a question names, by the words of its title and date that no other event shares ("Uri",
    "2020", "heat wave"), never by its ISO's name ("CAISO" is also the live grid). Returns (id, words matched)."""
    words = {e["id"]: _tokens(f'{e.get("title", "")} {e.get("when", "")} {e["id"]}') - _tokens(e.get("iso", ""))
             for e in events}
    asked = _tokens(question)
    scores = {}
    for eid, w in words.items():
        others = set().union(*(v for k, v in words.items() if k != eid))
        scores[eid] = len(asked & (w - others))
    best = max(scores, key=scores.get, default=None)
    if best is None or scores[best] == 0 or list(scores.values()).count(scores[best]) > 1:
        return None, 0
    return best, scores[best]


# ---------------------------------------------------------------------------------------------- formatting
def _clock(ts: Any, fmt: str = "%H:%M") -> str | None:
    """A runtime timestamp in its own offset (the ISO's local time)."""
    try:
        return datetime.fromisoformat(str(ts)).strftime(fmt)
    except ValueError:
        return None


def _ago(seconds: float) -> str:
    s = max(0.0, seconds)
    if s < 90:
        return f"{s:.0f} s ago"
    if s < 5400:
        return f"{s / 60:.0f} min ago"
    return f"{s / 3600:.1f} h ago"


def _mw(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"


_NUMBER = re.compile(r"\d{1,2}:\d{2}|\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


def _peak(points: list) -> tuple[str, float] | None:
    vals = [(t, v) for t, v in points or [] if v is not None]
    return max(vals, key=lambda p: p[1]) if vals else None


# ---------------------------------------------------------------------------------------------- answers
def grid_section(question: str, st: dict, now: float) -> str:
    g = st.get("grid")
    if not g:
        return "No live grid reading yet: the runtime has not fetched its ISO feed since it started (GET /api/state)."
    lines = []
    asked = [iso for iso in st.get("iso_options") or [] if re.search(rf"\b{iso}\b", question, re.IGNORECASE)]
    other = next((iso for iso in asked if iso != g["iso"]), None)
    if other:
        sc = st.get("scale") or {}
        if sc.get("iso") == other and sc.get("demand_mw") is not None:
            at = _clock(sc.get("demand_t"))
            lines.append(f"{NAME} is watching {g['iso']} right now (the operator switches it). For {other} I have its "
                         f"live system demand: {sc['demand_mw']:,.0f} MW{f' at {at} local' if at else ''} ({other} "
                         "via gridstatus; GET /api/state).")
        else:
            lines.append(f"{NAME} is watching {g['iso']} right now, not {other} (the operator switches it).")
    stale = ", STALE: the plan runs on last known data" if g.get("stale") else ""
    lines.append(f"{g['iso']} right now (node {g['location']}), from {NAME}'s live feed (GET /api/state, fetched "
                 f"{_ago(now - g['t'])}{stale}):")
    at = _clock(g.get("price_interval_start"))
    lines.append(f"- Real-time price: ${g['price_now']:.2f}/MWh{f' for the interval from {at} local' if at else ''}")
    curve = [(t, v) for t, v in g.get("price_curve") or [] if v is not None]
    if curve:
        hi_t, hi = max(curve, key=lambda p: p[1])
        lo = min(v for _, v in curve)
        when = _clock(hi_t, "%a %H:%M")
        lines.append(f"- Prices ahead ({g.get('price_curve_source') or 'price curve'}): ${lo:.2f} to ${hi:.2f}/MWh"
                     f"{f', highest from {when}' if when else ''}")
    if g.get("carbon_now") is not None:
        lines.append(f"- Carbon: {g['carbon_now']:.0f} gCO2/kWh from the live fuel mix")
    mix = sorted(((k, v) for k, v in (g.get("fuel_mix_mw") or {}).items() if v and v > 0), key=lambda kv: -kv[1])
    if mix:
        lines.append("- Fuel mix: " + ", ".join(f"{k} {v:,.0f} MW" for k, v in mix[:3]) + " (largest three)")
    peak = _peak(g.get("load_forecast"))
    if peak:
        when = _clock(peak[0], "%a %H:%M")
        lines.append(f"- Load forecast peak: {peak[1]:,.0f} MW{f' at {when}' if when else ''}")
    alerts = g.get("alerts") or []
    lines.append(f"- {g['iso']} alerts: " + ("; ".join(alerts) if alerts else "none"))
    caps = st.get("cap_events") or []
    if caps:
        for c in caps:
            start = _clock(c.get("start"))
            size = f"{c['target_w']:.1f} W" if c.get("target_w") is not None else f"{c.get('target_pct')}% below baseline"
            lines.append(f"- Power cap on this Mac: {size}{f' from {start}' if start else ''} for "
                         f"{c['duration_s'] // 60} min ({c['source']}: {c.get('reason') or 'no reason given'})")
    else:
        lines.append("- Power caps on this Mac: none")
    if not alerts and not caps:
        lines.append(f"No {g['iso']} alert and no cap in force, so {NAME} is running its normal price-and-carbon plan.")
    rp = st.get("replay") or {}
    if rp.get("active"):
        title = next((e["title"] for e in rp.get("events") or [] if e["id"] == rp["active"]), rp["active"])
        lines.append(f"A replay of {title} is running on the dashboard; the numbers above are today's live grid.")
    if g.get("source_urls"):
        lines.append(f"Source: {g['source_urls'][0]}")
    return "\n".join(lines)


def power_section(st: dict, now: float) -> str:
    p, plan = st.get("power"), st.get("plan") or {}
    lines = []
    if p:
        parts = [f"{k.upper()} {p[f'{k}_w']:.1f} W" for k in ("cpu", "gpu", "ane") if p.get(f"{k}_w") is not None]
        lines.append(f"This Mac draws {p['combined_w']:.1f} W ({', '.join(parts)}), measured by macOS powermetrics "
                     f"{_ago(now - p['t'])} (GET /api/state).")
    else:
        lines.append("No power reading yet: macOS powermetrics has not reported since the runtime started "
                     "(GET /api/state).")
    if plan.get("planned_w") is not None:
        cap = f"under a {plan['cap_w']:.1f} W cap" if plan.get("cap_w") is not None else "with no cap"
        lines.append(f"The plan for this slot expects {plan['planned_w']:.1f} W {cap} (planned from the calibration, "
                     "not measured).")
    for s in st.get("fleet") or []:
        if s.get("watts") is not None:
            lines.append(f"- {s['name']}: {s['watts']:.1f} W from its battery reading ({s['status']})")
    return "\n".join(lines)


_MODES = {"dispatcher": "dispatcher on", "baseline": "dispatcher off: everything runs, the baseline",
          "pause_all": "pause everything"}


def _job_line(a: dict, status: dict) -> str:
    line = f"- {a['job']}: {a['state']}"
    if a.get("device"):
        line += f" on the {a['device'].upper()}"
    if a.get("concurrency"):
        line += f" at concurrency {a['concurrency']}"
    if status.get("step") is not None and status.get("rate") is not None:
        line += f"; step {status['step']:,} at {status['rate']:.1f} steps/s"
    if status.get("items_done") is not None and status.get("total"):
        line += f"; {status['items_done']:,} of {status['total']:,} items"
    if status.get("ttft_p95_60s") is not None:
        line += f"; time to first token p95 {status['ttft_p95_60s']:.2f} s over the last minute"
    return line


def plan_section(st: dict) -> str:
    plan = st.get("plan")
    if not plan:
        return "No plan yet: the solver has not produced a schedule since the runtime started (GET /api/state)."
    at = _clock(plan.get("slot_start"))
    mode = _MODES.get(plan["mode"], plan["mode"])
    lines = [f"Plan for the slot{f' from {at} local' if at else ''} ({mode}), from GET /api/state:"]
    jobs = st.get("jobs") or {}
    lines += [_job_line(a, jobs.get(a["job"]) or {}) for a in plan.get("actions") or []]
    if plan.get("on_last_known_data"):
        lines.append("The grid feed is stale, so this plan is on last known data.")
    pending = [a for a in st.get("approvals") or [] if a.get("status") == "pending"]
    if pending:
        lines.append("Waiting for a person: " + "; ".join(f"{a['owner']} on {a['job_id']}" for a in pending))
    ex = st.get("explanation")
    if ex and ex.get("text"):
        lines.append(f"Why (the runtime's explanation of this schedule): {ex['text']}")
    return "\n".join(lines)


def why_reply(question: str, rt: Runtime, st: dict) -> str:
    note, src = "", "POST /api/ask, answered from the live state"
    try:
        ex = rt.ask(question)
    except Refused as e:
        ex, src = rt.explain(), "GET /api/explain"
        note = (f"The runtime is at its question limit for this Mac ({e.detail}), so here is its explanation of the "
                "current plan instead.\n\n" if e.status == 429 else
                f"The runtime did not take the question ({e.status}: {e.detail}), so here is its explanation of the "
                "current plan instead.\n\n")
    if not ex:
        return note + "No explanation yet: the solver has not produced a schedule since the runtime started."
    out = note + ex["text"]
    if ex.get("llm_used"):
        # The runtime rejects a worded answer that adds a number; show the facts its numbers come from.
        used = _numbers(ex["text"])
        cited = [f for f in ex.get("facts") or [] if _numbers(f) & used]
        out += (f"\n\nWorded by the runtime's model from the live facts ({src}); the facts its numbers come from:\n"
                + "\n".join(f"- {f}" for f in cited) if cited else f"\n\n(Worded by the runtime's model; {src}.)")
    elif ex.get("facts"):
        out += f"\n\n(The runtime's own facts, verbatim; {src}.)"
    if st.get("plan"):
        out += "\n\n" + plan_section({**st, "explanation": None})
    return out


def event_reply(e: dict, st: dict) -> str:
    lines = [f"{e['title']} ({e['when']}, {e['iso']}), from {NAME}'s replay catalog (GET /api/replay/events):"]
    lines += [f"- {i['text']} ({i['source']})" for i in e.get("impact") or []]
    lines += [f"- {a['label']} ({a['source']})" for a in e.get("alerts") or [] if a.get("kind") == "brownout"]
    rp = st.get("replay") or {}
    last = rp.get("last") or {}
    if last.get("event") == e["id"]:
        where = (f"in the replay running now ({last.get('progress', 0):.0%} through)" if rp.get("active") == e["id"]
                 else "in the last replay on this Mac")
        sc = last.get("scale")
        if last.get("nothing_to_shed"):
            lines.append(f"What {NAME} would have freed: {where}, this Mac had nothing flexible running to "
                         "shed, so there is no cut to scale.")
        elif sc and last.get("measured_cut_pct") is not None:
            people = (f"; at the event's own ratio, about {sc['people']:,} {sc.get('people_unit') or 'people'}'s "
                      "worth of load" if sc.get("people") else "")
            shed = (f", {sc['share_of_shed_pct']:.1f}% of the {_mw(e['shed_mw'])} MW shed"
                    if sc.get("share_of_shed_pct") is not None and e.get("shed_mw") else "")
            lines.append(
                f"What {NAME} would have freed: {where}, {NAME} cut this Mac's measured power by "
                f"{last['measured_cut_pct']:.1f}% ({last['baseline_w']:.2f} W before the call, {last['ours_w']:.2f} W "
                f"during it, macOS powermetrics; GET /api/state). Credited at {sc['share_pct']:.1f}% (the cut the alert "
                f"asked, as far as it was delivered) on the {_mw(sc['flexible_mw'])} MW of flexible load "
                f"({sc['flexible_source']}), that is about {sc['freed_mw']:,.0f} MW{shed}{people}. ESTIMATE: arithmetic "
                "on cited numbers and one laptop's measured cut, not a data center's.")
        else:
            lines.append(f"What {NAME} would have freed: {where}, no cut had been measured yet.")
    else:
        lines.append(f"What {NAME} would have freed: not measured yet, because this event has not been replayed since "
                     "the runtime started. At the table its real EIA-930 hours run through the live software and "
                     f"this Mac's cut is measured; {NAME} then scales that cut to the {_mw(e['flexible_mw'])} MW of "
                     f"flexible load ({e['flexible_source']}). I can't start a replay myself.")
    lines.append(f"Grid data: {e['data_source']}. Report: {e['report_url']}")
    return "\n".join(lines)


def events_list(events: list[dict]) -> str:
    lines = [f"The real grid emergencies {NAME} replays (GET /api/replay/events); ask about one by name:"]
    for e in events:
        first = (e.get("impact") or [None])[0]
        lines.append(f"- {e['title']} ({e['when']}, {e['iso']})" +
                     (f": {first['text']} ({first['source']})" if first else ""))
    lines.append("At the table a judge replays one: its real EIA-930 hours run through the live software and this "
                 "Mac's cut is measured. I can't start one.")
    return "\n".join(lines)


def answer(text: str, rt: Runtime, now: float | None = None) -> str:
    """The reply to one chat message. Every number in it comes from the runtime's read routes."""
    q = " ".join(text.split())
    if not q or _HELLO.match(q):
        return HELP
    if _OVERRIDE.search(q):
        return REFUSE_OVERRIDE
    if acting(q):
        return REFUSE
    now = time.time() if now is None else now
    try:
        st = rt.state()
        eid, matched = match_event(q, (st.get("replay") or {}).get("events") or [])
        if (eid and (matched >= 2 or not _LIVE.search(q))) or _EVENT.search(q):
            events = rt.events()
            e = next((x for x in events if x["id"] == eid), None)
            return event_reply(e, st) if e else events_list(events)
        if _WHY.search(q):
            return why_reply(q, rt, st)
        parts = []
        if _GRID.search(q):
            parts.append(grid_section(q, st, now))
        if _POWER.search(q):
            parts.append(power_section(st, now))
        if _PLAN.search(q):
            parts.append(plan_section(st))
        return "\n\n".join(parts) if parts else why_reply(q, rt, st)
    except (RuntimeDown, Refused):
        return DOWN


# ---------------------------------------------------------------------------------------------- the uAgent
def register(agent, seed: str, key: str) -> str | None:
    """Create this agent's Agentverse mailbox and profile with the API key: what the Inspector's Connect, then
    Mailbox, does in a browser. Returns None, or why it failed (never the key)."""
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
        register_agent(AgentverseRegistrationRequest(name=NAME, endpoint=av.mailbox_endpoint, type="mailbox",
                                                     protocols=list(agent.protocols), description=DESCRIPTION,
                                                     readme=README, starter_prompts=STARTERS,
                                                     track_interactions=False),
                       av, RegistrationRequestCredentials(agentverse_api_key=key, agent_seed_phrase=seed))
    except AgentverseRequestError as e:
        return str(e) or e.from_exc.__class__.__name__
    except requests.RequestException as e:          # its first lookup is not wrapped in AgentverseRequestError
        return f"could not reach Agentverse ({e.__class__.__name__})"
    return None


def build_agent(seed: str, key: str, rt: Runtime, port: int):
    import uagents.asgi
    from uagents import Agent, Context, Protocol
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement,
        ChatMessage,
        EndSessionContent,
        TextContent,
        chat_protocol_spec,
    )

    # uagents serves its local routes (the Inspector's /connect among them) on every interface. The venue network
    # has strangers on it and mailbox mode needs no inbound connection, so listen on loopback only.
    uagents.asgi.HOST = "127.0.0.1"
    agent = Agent(name=NAME, seed=seed, port=port, mailbox=True, description=DESCRIPTION)
    chat = Protocol(spec=chat_protocol_spec)

    def utcnow() -> datetime:
        return datetime.now(UTC)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=utcnow(), acknowledged_msg_id=msg.msg_id))
        text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
        if not text:
            return                                    # a session start or end only: nothing was asked
        ctx.logger.info(f"[inbound] {sender[:16]}...: {text[:120]!r}")
        reply = await asyncio.to_thread(answer, text, rt)
        await ctx.send(sender, ChatMessage(timestamp=utcnow(), msg_id=uuid4(),
                                           content=[TextContent(type="text", text=reply),
                                                    EndSessionContent(type="end-session")]))
        ctx.logger.info(f"[outbound] {len(reply)} characters to {sender[:16]}...")

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(f"[inbound] {sender[:16]}... read {msg.acknowledged_msg_id}")

    agent.include(chat, publish_manifest=True)

    if key:                                           # without one, main() has said how to add it
        @agent.on_event("startup")
        async def connect(ctx: Context):
            why = await asyncio.to_thread(register, agent, seed, key)
            if why:
                ctx.logger.error(f"Agentverse registration failed: {why} (docs/fetch-agent.md, 'If it fails')")
            else:
                ctx.logger.info(f"Registered on Agentverse with a mailbox: find {NAME} in ASI:One "
                                "(docs/fetch-agent.md)")

    return agent


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    seed, key = os.getenv("FETCH_AGENT_SEED", "").strip(), os.getenv("AGENTVERSE_API_KEY", "").strip()
    if not seed:
        print(NO_SEED, file=sys.stderr)
        return 2
    rt = Runtime(f"http://127.0.0.1:{os.getenv('PORT', '8080')}")
    try:
        rt.state()
        print(f"Runtime answering at {rt.base_url}; this agent may only call: "
              + ", ".join(f"{m} {p}" for m, p in sorted(READS)))
    except (RuntimeDown, Refused):
        print(f"Runtime not answering at {rt.base_url} yet: replies say so until `make demo` is up.")
    if not key:
        print(NO_KEY)
    agent = build_agent(seed, key, rt, int(os.getenv("FETCH_AGENT_PORT", "8001")))
    print(f"{NAME} agent address: {agent.address}")
    agent.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
