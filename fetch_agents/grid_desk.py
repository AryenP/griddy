"""Griddy Grid Desk (team/2-anuraag.md FA2): the utility's side of the deal and the only agent a judge talks to in
ASI:One. It answers "how stressed is the grid?" from the live runtime (GET /api/state, with source and age), reads a
cut request with a regex ("I need 30% off for 20 minutes"; one question back if it is unclear), sends it to Griddy
Facility, and relays every step in plain words: sent, the facility's offer, waiting for its operator, approved or
refused (with the operator's words), then Griddy Verifier's meter check.

Every number it says comes from a runtime route or the Verifier, with its source. If something is down it says so
and gives no number. It asks for nothing else: requests to pause, switch, approve or break are refused. No language
model is used anywhere in the flow."""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

if __package__ in (None, ""):                         # `python fetch_agents/grid_desk.py` from make fetch-three
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.channels import fetch_agent as fa  # noqa: E402  (standard library and httpx only at its top)
from fetch_agents.common import (  # noqa: E402
    NAMES, PROTOCOL, ROOT, Loopback, RateLimit, Refused, RuntimeDown, address_of, allowed, connect_on_startup, models,
    runtime_url,
)

NAME = NAMES["grid_desk"]
CALLS = frozenset({("GET", "/api/state")})
VERIFY_AFTER_S = 60.0     # ask the Verifier this long after the cap applies: long enough for a 10-s mean to settle

DESCRIPTION = ("The utility's desk for Griddy (Cal Hacks 13): ask how stressed the grid is, or ask a facility for a "
               "power cut. A second agent, the facility, offers what it can do; nothing applies until its human "
               "operator approves; a third agent checks the facility's meter.")
STARTERS = ["How stressed is the CAISO grid right now?", "I need 30% off for 20 minutes",
            "What is the facility drawing right now?", "Did the cut hold?"]
README = f"""![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# {NAME}

A demand-response deal between three agents, on a real laptop running Griddy (Cal Hacks 13):
1. **{NAME}** (this agent, the utility side): ask it about the live grid, or ask for a cut.
2. **{NAMES['facility']}** (the laptop): stages the cut in Griddy's own intake and offers what its solver can do.
   Nothing applies until its human operator approves on the operator page.
3. **{NAMES['verifier']}**: reads the laptop's measured watts (macOS powermetrics) from the run's timeline and
   reports whether the cap held, with the run id so anyone can recompute it.

Every number comes from the live runtime or the meter, with its source. No language model makes a decision.
"""
HELP = (f"I'm {NAME}, the utility's side of a demand-response deal with a real laptop running Griddy. Ask me how "
        "stressed the grid is, or ask for a cut, e.g. \"I need 30% off for 20 minutes\". The facility's agent offers "
        "what it can do, its human operator approves or refuses, and an independent agent checks the meter.")
REFUSE = ("I can only ask the facility for a power cut and report what happens. I can't pause jobs, switch grids or "
          "approve anything: the facility's operator decides on their own page.")
DOWN = "Griddy's runtime is not answering, so I have no live numbers to give, and I won't make any up."

_WORDS = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15,
          "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
_CUT = re.compile(r"\b(?:off|cut|reduce|reduction|less|lower|shed|curtail\w*|drop|down|back|cap|limit)\b|%|\bpercent\b|"
                  r"\bhalf\s+(?:of\s+)?(?:your|its|the)\b", re.IGNORECASE)
_PCT = re.compile(rf"{_NUM}\s*(?:%|percent\b|per\s*cent\b)", re.IGNORECASE)
_HALF = re.compile(r"\bhalf\s+(?:of\s+)?(?:your|its|the)?\s*(?:draw|power|load|usage|consumption)\b", re.IGNORECASE)
_WATTS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:w|watts?)\b", re.IGNORECASE)
_BIG = re.compile(r"\d\s*(?:kw|mw|gw|kilowatts?|megawatts?)\b", re.IGNORECASE)
_MIN = re.compile(rf"{_NUM}\s*(?:minutes?|mins?|m)\b", re.IGNORECASE)
_HOUR = re.compile(rf"(?:{_NUM}\s*(?:hours?|hrs?|h)\b|\b(half)\s+an?\s+hour\b)", re.IGNORECASE)
_VERIFY = re.compile(r"\b(?:verif\w*|verdict|meter|did (?:it|the cut|the cap) (?:hold|work)|hold)\b", re.IGNORECASE)
_STATUS = re.compile(r"\b(?:status|update|where are we|any news|what happened)\b", re.IGNORECASE)


def _n(s: str) -> float:
    return float(_WORDS[s.lower()]) if s.lower() in _WORDS else float(s)


def parse_cut(text: str) -> dict | None:
    """A cut request read by rule: {"target_pct" | "target_w", "duration_s"}, or {"ask": question} when one part is
    missing or out of range, or None when the message is not a cut request."""
    if not _CUT.search(text) or not re.search(r"\d|%|\bpercent\b|\bhalf\b", text, re.IGNORECASE):
        return None                                   # "turn off the dispatcher" is an instruction, not a cut
    pct = _PCT.search(text)
    watts = None if pct else _WATTS.search(text)
    half = None if pct or watts else _HALF.search(text)
    if not (pct or watts or half):
        if _BIG.search(text):
            return {"ask": "This facility is one laptop, so its cap is in watts. Say a percent (\"30% off\") or watts."}
        return {"ask": "How much? Say a percent below what it draws now (\"30% off\") or a cap in watts (\"10 W\")."}
    m, h = _MIN.search(text), _HOUR.search(text)
    if m:
        dur = _n(m.group(1)) * 60
    elif h:
        dur = 1800.0 if h.group(2) else _n(h.group(1)) * 3600
    else:
        return {"ask": "For how long? e.g. \"for 20 minutes\"."}
    if not 60 <= dur <= 4 * 3600:
        return {"ask": "Say a duration between 1 minute and 4 hours."}
    if pct or half:
        v = 50.0 if half else _n(pct.group(1))
        if not 1 <= v <= 90:
            return {"ask": "Say a cut between 1% and 90%."}
        return {"target_pct": v, "duration_s": int(dur)}
    w = float(watts.group(1))
    if w <= 0:
        return {"ask": "Say a cap above 0 W."}
    return {"target_w": w, "duration_s": int(dur)}


def _when(v) -> str:
    try:
        t = datetime.fromtimestamp(v) if isinstance(v, (int, float)) else datetime.fromisoformat(str(v))
        return t.strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "an unknown time"


def offer_text(o) -> str:
    if o.status == "offered":
        acts = "; ".join(o.actions) if o.actions else "the plan preview had no slot to show"
        target = f" Target: {o.target_w:.1f} W." if o.target_w is not None else ""
        return (f"{NAMES['facility']}'s offer, from its own intake and solver: {o.readback}{target} In its plan: "
                f"{acts}. Nothing moves until the facility's operator approves it on the operator page (approval "
                f"{o.approval_id}). Waiting for the facility's operator.")
    if o.status == "clarify":
        return f"The facility asks: {o.message or 'please say how much and for how long'}"
    if o.status == "down":
        return f"{NAMES['facility']} could not reach its runtime, so there is no offer and no number."
    return f"{NAMES['facility']} declined: {o.message or 'no reason given'}."


def outcome_text(o, verify_after_s: float) -> str:
    who = f" by {o.who}" if o.who else ""
    said = f' ("{o.words}")' if o.words else ""
    if o.accepted:
        size = f"{o.target_w:.1f} W" if o.target_w is not None else "the cap"
        return (f"Approved{who}{said}. The cap of {size} started at {_when(o.cap_start)} (Griddy's timeline). I'll ask "
                f"{NAMES['verifier']} to read the meter in {verify_after_s:.0f} s.")
    if o.status == "refused":
        return f"Refused{who}{said}. Nothing was applied: the facility keeps running as planned."
    if o.status in ("timeout", "expired"):
        return "No answer from the facility's operator in time. Nothing was applied."
    if o.status == "down":
        return f"{NAMES['facility']} lost its runtime while waiting. Nothing is known to have been applied."
    return f"The operator answered \"{o.status}\"{said}. Nothing was applied."


def verdict_text(v) -> str:
    src = f"run {v.run_id}, {v.file}" if v.file else f"run {v.run_id or 'unknown'}"
    if not v.measured:
        return f"{NAMES['verifier']}: not measured ({v.note or 'no power rows'}), so no number. Source: {src}."
    parts = [f"{NAMES['verifier']} read the meter itself (macOS powermetrics rows in {src}):"]
    if v.baseline_w is not None:
        parts.append(f"- 60 s before the cap: {v.baseline_w:.1f} W")
    parts.append(f"- since the cap started: {v.mean_w:.1f} W on average over {v.samples} samples")
    if v.under_cap_pct is not None:
        parts.append(f"- {v.under_cap_pct:.0f}% of samples at or under {v.target_w:.1f} W")
    parts.append(f"- compliant {v.time_to_compliance_s:.0f} s after the start (10-s mean at or under the cap)"
                 if v.time_to_compliance_s is not None else "- the 10-s mean has not reached the cap yet")
    parts.append("Anyone can recompute this from the same file (the reporter's rules, as in `make verify`).")
    return "\n".join(parts)


class Desk:
    """The decisions, without uagents. Each handler returns what to send: (to, payload, delay_s), where a str payload
    is a chat message to the judge and a model is a message to another agent."""

    def __init__(self, rt: Loopback, M, facility: str | None, verifier: str | None,
                 verify_after_s: float = VERIFY_AFTER_S):
        self.rt, self.M, self.facility, self.verifier, self.verify_after_s = rt, M, facility, verifier, verify_after_s
        self.session: dict[str, dict] = {}            # judge -> the deal in flight
        self.judge_of: dict[str, str] = {}            # request id -> judge
        self.limit = RateLimit(n=6, per_s=60)

    def on_judge(self, judge: str, text: str, now: float | None = None) -> list[tuple]:
        now = time.time() if now is None else now
        text = (text or "").strip()
        if not self.limit.allow(judge, now):
            return [(judge, "That's a lot of messages in a minute: give me a moment.", 0)]
        if not text or fa._HELLO.match(text):
            return [(judge, HELP, 0)]
        if fa._OVERRIDE.search(text):
            return [(judge, fa.REFUSE_OVERRIDE, 0)]
        deal = self.session.get(judge)
        cut = parse_cut(text)
        if cut is not None and not _VERIFY.search(text):
            if "ask" in cut:
                return [(judge, cut["ask"], 0)]
            if deal and not deal.get("done"):
                return [(judge, f"A request is already with the facility ({deal['req'].id}): {self._stage(deal)}", 0)]
            if not self.facility:
                return [(judge, "The facility's address is not configured on this desk, so I can't send it.", 0)]
            req = self.M.CurtailmentRequest(id=f"cut-{uuid4().hex[:8]}", duration_s=cut["duration_s"],
                                            target_pct=cut.get("target_pct"), target_w=cut.get("target_w"),
                                            reason="asked by the grid desk on ASI:One", requested_by=NAME)
            self.session[judge] = {"req": req, "stage": "sent"}
            self.judge_of[req.id] = judge
            size = f"{req.target_pct:g}% below what it draws now" if req.target_pct is not None else f"a {req.target_w:g} W cap"
            return [(self.facility, req, 0),
                    (judge, f"Sent to {NAMES['facility']}: {size} for {req.duration_s // 60} minutes ({req.id}). "
                            "Waiting for its offer.", 0)]
        if deal and _VERIFY.search(text):
            o = deal.get("outcome")
            if o is None or not o.accepted:
                return [(judge, f"Nothing to verify yet: {self._stage(deal)}", 0)]
            return [(self.verifier, self._verify(deal), 0), (judge, f"Asked {NAMES['verifier']} to read the meter.", 0)]
        if deal and _STATUS.search(text):
            return [(judge, self._stage(deal), 0)]
        if fa.acting(text):
            return [(judge, REFUSE, 0)]
        return [(judge, self._live(text, now), 0)]

    def _live(self, text: str, now: float) -> str:
        try:
            st = self.rt.call("GET", "/api/state")
        except (RuntimeDown, Refused):
            return DOWN
        parts = [fa.grid_section(text, st, now)]
        if fa._POWER.search(text) or re.search(r"\b(?:facility|mac|laptop)\b", text, re.IGNORECASE):
            parts.append(fa.power_section(st, now))
        return "\n\n".join(parts)

    def _stage(self, deal: dict) -> str:
        return {"sent": "sent, waiting for the facility's offer",
                "offered": "offered, waiting for the facility's operator",
                "applied": "approved and applied, the meter check is next",
                "done": "finished"}.get(deal["stage"], deal["stage"])

    def _verify(self, deal: dict):
        o = deal["outcome"]
        return self.M.VerifyRequest(request_id=deal["req"].id, run_id=o.run_id, cap_id=o.cap_id, target_w=o.target_w)

    def _deal(self, sender: str, expected: str | None, request_id: str):
        if not allowed(sender, {expected}):
            return None, None
        judge = self.judge_of.get(request_id)
        return judge, self.session.get(judge) if judge else None

    def on_offer(self, sender: str, offer) -> list[tuple]:
        judge, deal = self._deal(sender, self.facility, offer.request_id)
        if deal is None:
            return []
        deal["stage"] = "offered" if offer.status == "offered" else "done"
        deal["done"] = offer.status != "offered"
        return [(judge, offer_text(offer), 0)]

    def on_outcome(self, sender: str, outcome) -> list[tuple]:
        judge, deal = self._deal(sender, self.facility, outcome.request_id)
        if deal is None:
            return []
        deal["outcome"] = outcome
        out = [(judge, outcome_text(outcome, self.verify_after_s), 0)]
        if outcome.accepted and self.verifier:
            deal["stage"] = "applied"
            out.append((self.verifier, self._verify(deal), self.verify_after_s))
        else:
            deal["stage"], deal["done"] = "done", True
        return out

    def on_verdict(self, sender: str, verdict) -> list[tuple]:
        judge, deal = self._deal(sender, self.verifier, verdict.request_id)
        if deal is None:
            return []
        deal["stage"], deal["done"] = "done", True
        return [(judge, verdict_text(verdict), 0)]


# ---------------------------------------------------------------------------------------------- the uAgent
def main() -> int:
    from dotenv import load_dotenv
    from uagents import Agent, Context, Model, Protocol
    from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec
    import uagents.asgi

    load_dotenv(ROOT / ".env")
    seed, key = os.getenv("FETCH_GRID_DESK_SEED", "").strip(), os.getenv("AGENTVERSE_API_KEY", "").strip()
    if not seed:
        print("FETCH_GRID_DESK_SEED is empty in .env (docs/judging/fetch-three-agents.md, setup).", file=sys.stderr)
        return 2
    M = models(Model)
    desk = Desk(Loopback(runtime_url(), CALLS), M, address_of("facility"), address_of("verifier"))
    uagents.asgi.HOST = "127.0.0.1"                   # mailbox mode needs no inbound connection
    agent = Agent(name=NAME, seed=seed, port=int(os.getenv("FETCH_GRID_DESK_PORT", "8002")), mailbox=True,
                  description=DESCRIPTION)
    chat, deal = Protocol(spec=chat_protocol_spec), Protocol(name=PROTOCOL[0], version=PROTOCOL[1])

    async def send_all(ctx: Context, out: list[tuple]):
        for to, payload, delay in out:
            if delay:
                asyncio.get_running_loop().create_task(_later(ctx, to, payload, delay))
            elif isinstance(payload, str):
                await ctx.send(to, ChatMessage(timestamp=datetime.now(UTC), msg_id=uuid4(),
                                               content=[TextContent(type="text", text=payload)]))
            else:
                await ctx.send(to, payload)

    async def _later(ctx: Context, to: str, payload, delay: float):
        await asyncio.sleep(delay)
        await send_all(ctx, [(to, payload, 0)])

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(UTC), acknowledged_msg_id=msg.msg_id))
        text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
        if text:
            ctx.logger.info(f"[judge] {sender[:16]}...: {text[:120]!r}")
            await send_all(ctx, await asyncio.to_thread(desk.on_judge, sender, text))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(f"{sender[:16]}... read {msg.acknowledged_msg_id}")

    @deal.on_message(M.Offer)
    async def on_offer(ctx: Context, sender: str, msg):
        await send_all(ctx, desk.on_offer(sender, msg))

    @deal.on_message(M.Outcome)
    async def on_outcome(ctx: Context, sender: str, msg):
        await send_all(ctx, desk.on_outcome(sender, msg))

    @deal.on_message(M.Verdict)
    async def on_verdict(ctx: Context, sender: str, msg):
        await send_all(ctx, desk.on_verdict(sender, msg))

    agent.include(chat, publish_manifest=True)
    agent.include(deal, publish_manifest=True)
    connect_on_startup(agent, seed, key, NAME, DESCRIPTION, README, STARTERS)
    print(f"{NAME} address: {agent.address}; it may only call GET /api/state; facility "
          f"{desk.facility or 'not configured'}, verifier {desk.verifier or 'not configured'}")
    agent.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
