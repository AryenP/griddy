"""Griddy Facility (team/2-anuraag.md FA3): this Mac's side of the deal. It accepts curtailment requests from Grid Desk
only, stages each one in Griddy's own intake as a pending operator approval, answers with the solver's real offer,
then waits for the operator's answer and reports it. It never decides anything itself.

It makes exactly two calls, on loopback, and any other raises NotAllowed before a request is built:
  - POST /request with "source": "fetch" (machine 1's contract, team/1-aryen.md "Fetch three-agent support"): the
    intake parses the request as usual but does not apply it; it becomes a pending operator approval, and the
    response carries `staged: true`, the approval id, the readback and a schedule preview.
  - GET /api/approvals?owner=<operator>&status= for that approval: pending, then approved, refused or expired.

The operator answers on the operator page, or in the ASI:One chat (Fetch asks for the whole flow inside ASI:One):
Grid Desk passes their words on as an OperatorAnswer, and a second client whose only call is
POST /api/approvals/{id}/reply hands them, as typed, to the same reader the operator page uses. That reader takes a
plain "yes" or "no, <reason>" by rule, never a model's reading, and only for a request staged here.

A response without a staged approval means the runtime does not know the contract (it would have applied the
request on its own): Facility says so, stops offering, and the runbook says not to run it against that runtime."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):                         # `python fetch_agents/facility.py` from make fetch-three
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_agents.common import (  # noqa: E402
    BADGES, NAMES, PROTOCOL, ROOT, WHO, Loopback, RateLimit, Refused, RuntimeDown, address_of, allowed,
    answer_models, connect_on_startup, models, runtime_url,
)

NAME = NAMES["facility"]
CALLS = frozenset({("POST", "/request"), ("GET", "/api/approvals")})
REPLY_CALLS = frozenset({("POST", "/api/approvals/{id}/reply")})     # the operator's words from the chat, nothing else
ANSWERED_IN = "the facility's operator, in ASI:One"
UNCLEAR = 'Not understood: reply with a plain "yes", or "no, <reason>".'
ABOUT = "This Mac's side of a demand-response deal: stages a cut for its operator, never applies it on its own."
README = f"""{BADGES}
# {NAME}

This laptop's side of a demand-response deal (Griddy, Cal Hacks 13). It takes a cut request from Griddy Grid Desk
only, stages it in Griddy's own intake, and offers what its solver can do. Nothing applies until its human operator
answers: a plain "yes", or "no" with a reason, in the ASI:One chat or on the operator page. Talk to Griddy Grid Desk.
"""
POLL_S = 3.0              # how often to look for the operator's answer
TIMEOUT_S = 15 * 60       # after this, report that no answer came


def request_text(req) -> str:
    """The request in the plain words the intake already reads by rule ("30% off for 20 minutes"), so no model is
    needed to parse it."""
    mins = max(1, round(req.duration_s / 60))
    size = f"{req.target_pct:g}% off" if req.target_pct is not None else f"a cap of {req.target_w:g} W"
    why = f" Reason: {req.reason}." if req.reason else ""
    return f"Grid request: {size} for the next {mins} minutes.{why}"


def offer_actions(schedule: dict | None, start: str | None) -> list[str]:
    """What the preview schedule does with each job in the slot the cap starts in: facts from the solver, worded."""
    if not schedule or not schedule.get("slots"):
        return []
    slots, minutes = schedule["slots"], schedule.get("slot_minutes", 15)
    t = datetime.fromisoformat(start).timestamp() if start else time.time()
    i = next((k for k, s in enumerate(slots) if datetime.fromisoformat(s).timestamp() <= t
              < datetime.fromisoformat(s).timestamp() + minutes * 60), 0)
    out = []
    for job, row in sorted((schedule.get("assignments") or {}).items()):
        a = row[i] if i < len(row) else {}
        if not a.get("run"):
            out.append(f"{job} pauses")
        else:
            conc = f" at concurrency {a['concurrency']}" if job == "chat" and a.get("concurrency") else ""
            out.append(f"{job} runs on {a.get('device') or 'gpu'}{conc}")
    planned = (schedule.get("planned_w") or [None])[i] if i < len(schedule.get("planned_w") or []) else None
    if planned is not None:
        out.append(f"planned {planned:.1f} W in that slot (calibrated, not measured)")
    return out


class Facility:
    """The decisions, without uagents. `pending` maps a request id to what Facility is waiting on."""

    def __init__(self, rt: Loopback, M, desk: str | None, relay: Loopback | None = None):
        self.rt, self.M, self.desk, self.relay = rt, M, desk, relay
        self.A = answer_models(M.Offer.__base__)      # the chat-answer messages, on the same base as M
        self.pending: dict[str, dict] = {}
        self.broken = False                           # the runtime applied a request without staging it
        self.limit = RateLimit(n=6, per_s=60)

    def on_request(self, sender: str, req, now: float | None = None):
        """The Offer for a CurtailmentRequest, or None: a sender that is not Grid Desk is dropped."""
        if not allowed(sender, {self.desk}):
            return None
        if not self.limit.allow(sender, now):
            return self.M.Offer(request_id=req.id, status="rejected", message="too many requests in a minute: wait")
        if self.broken:
            return self.M.Offer(request_id=req.id, status="error",
                                message="this facility stopped taking requests: its runtime does not stage them")
        if (req.target_pct is None) == (req.target_w is None):
            return self.M.Offer(request_id=req.id, status="clarify", message="say either a percent or watts")
        try:
            r = self.rt.call("POST", "/request", {"text": request_text(req), "who": WHO, "source": "fetch"})
        except (RuntimeDown, Refused) as e:
            why = e.detail if isinstance(e, Refused) else "the facility's runtime is not answering"
            return self.M.Offer(request_id=req.id, status="down" if isinstance(e, RuntimeDown) else "rejected",
                                message=why)
        intake = r.get("intake") or {}
        if intake.get("kind") == "clarify":
            return self.M.Offer(request_id=req.id, status="clarify", readback=intake.get("readback", ""),
                                message=intake.get("question") or "")
        if intake.get("kind") != "cap_event":
            return self.M.Offer(request_id=req.id, status="rejected", readback=intake.get("readback", ""),
                                message=intake.get("reason") or f"the intake read it as {intake.get('kind')}, not a cut")
        approval = r.get("approval") or {}
        aid = r.get("approval_id") or approval.get("id")
        if r.get("staged") is not True or not aid:
            self.broken = True
            return self.M.Offer(request_id=req.id, status="error", readback=intake.get("readback", ""),
                                message="the facility's runtime did not stage this request for its operator, so it may "
                                        "have applied it on its own: stop and check the runtime's version")
        cap = intake.get("cap_event") or {}
        self.pending[req.id] = {"approval_id": aid, "owner": approval.get("owner") or r.get("owner"), "cap": cap,
                                "run_id": r.get("run_id"), "since": time.time() if now is None else now}
        return self.M.Offer(request_id=req.id, status="offered", readback=intake.get("readback", ""),
                            target_w=cap.get("target_w"), actions=offer_actions(r.get("schedule"), cap.get("start")),
                            needs_approval=True, approval_id=aid)

    def on_answer(self, sender: str, ans):
        """The operator's words from the ASI:One chat, handed to the runtime as typed: an AnswerResult, or None for a
        sender that is not Grid Desk. A yes or no shows up as the Outcome on the next look (`check`)."""
        if not allowed(sender, {self.desk}):
            return None
        p = self.pending.get(ans.request_id)
        if p is None:
            return self.A.AnswerResult(request_id=ans.request_id, ok=False,
                                       message="there is no request waiting for the operator")
        if self.relay is None:
            return self.A.AnswerResult(request_id=ans.request_id, ok=False,
                                       message="answers in the chat are not set up here: use the operator page")
        try:
            r = self.relay.call("POST", "/api/approvals/{id}/reply", path_args={"id": p["approval_id"]},
                                body={"text": ans.text, "who": ANSWERED_IN, "owner": p["owner"]})
        except Refused as e:
            return self.A.AnswerResult(request_id=ans.request_id, ok=False, message=e.detail or f"HTTP {e.status}")
        except RuntimeDown:
            return self.A.AnswerResult(request_id=ans.request_id, ok=False,
                                       message="the facility's runtime is not answering")
        if ((r or {}).get("decision") or {}).get("decision") == "unclear":
            return self.A.AnswerResult(request_id=ans.request_id, ok=False, message=UNCLEAR)
        return self.A.AnswerResult(request_id=ans.request_id, ok=True)

    def check(self, request_id: str, now: float | None = None):
        """One look at the operator's answer: the Outcome once there is one, else None."""
        p = self.pending.get(request_id)
        if p is None:
            return None
        now = time.time() if now is None else now
        try:
            rows = self.rt.call("GET", "/api/approvals", params={"owner": p["owner"] or "", "status": ""})
        except (RuntimeDown, Refused):
            if now - p["since"] > TIMEOUT_S:
                del self.pending[request_id]
                return self.M.Outcome(request_id=request_id, accepted=False, status="down")
            return None
        row = next((a for a in rows or [] if a.get("id") == p["approval_id"]), None)
        status = (row or {}).get("status", "pending")
        if status == "pending":
            if now - p["since"] > TIMEOUT_S:
                del self.pending[request_id]
                return self.M.Outcome(request_id=request_id, accepted=False, status="timeout")
            return None
        del self.pending[request_id]
        cap = row.get("cap_event") or p["cap"]        # the cap as applied, when the runtime reports it
        words = next((row.get(k) for k in ("reply", "raw", "reason", "why") if row.get(k)), "")
        return self.M.Outcome(request_id=request_id, accepted=status == "approved", status=status, words=str(words),
                              who=str(row.get("who") or ""), cap_id=cap.get("id"), cap_start=cap.get("start"),
                              target_w=cap.get("target_w"), duration_s=cap.get("duration_s"),
                              run_id=row.get("run_id") or p["run_id"])


# ---------------------------------------------------------------------------------------------- the uAgent
def main() -> int:
    from dotenv import load_dotenv
    from uagents import Agent, Context, Model, Protocol
    import uagents.asgi

    load_dotenv(ROOT / ".env")
    seed, key = os.getenv("FETCH_FACILITY_SEED", "").strip(), os.getenv("AGENTVERSE_API_KEY", "").strip()
    if not seed:
        print("FETCH_FACILITY_SEED is empty in .env (docs/judging/fetch-three-agents.md, setup).", file=sys.stderr)
        return 2
    M, desk = models(Model), address_of("grid_desk")
    brain = Facility(Loopback(runtime_url(), CALLS), M, desk, relay=Loopback(runtime_url(), REPLY_CALLS))
    uagents.asgi.HOST = "127.0.0.1"
    agent = Agent(name=NAME, seed=seed, port=int(os.getenv("FETCH_FACILITY_PORT", "8003")), mailbox=True,
                  description=ABOUT)
    proto = Protocol(name=PROTOCOL[0], version=PROTOCOL[1])

    async def await_operator(ctx: Context, sender: str, request_id: str):
        while request_id in brain.pending:
            await asyncio.sleep(POLL_S)
            outcome = await asyncio.to_thread(brain.check, request_id)
            if outcome is not None:
                ctx.logger.info(f"outcome for {request_id}: {outcome.status}")
                await ctx.send(sender, outcome)

    @proto.on_message(M.CurtailmentRequest, replies=M.Offer)
    async def on_request(ctx: Context, sender: str, msg):
        offer = await asyncio.to_thread(brain.on_request, sender, msg)
        if offer is None:
            ctx.logger.warning(f"dropped a request from {sender[:16]}...: not Grid Desk")
            return
        ctx.logger.info(f"offer for {msg.id}: {offer.status} {offer.approval_id or ''}")
        await ctx.send(sender, offer)
        # uagents handles one message at a time: wait in the background so the operator's answer can arrive
        asyncio.get_running_loop().create_task(await_operator(ctx, sender, msg.id))

    @proto.on_message(brain.A.OperatorAnswer, replies=brain.A.AnswerResult)
    async def on_answer(ctx: Context, sender: str, msg):
        result = await asyncio.to_thread(brain.on_answer, sender, msg)
        if result is None:
            ctx.logger.warning(f"dropped an answer from {sender[:16]}...: not Grid Desk")
            return
        ctx.logger.info(f"operator answer for {msg.request_id} from the chat: {'read' if result.ok else result.message}")
        await ctx.send(sender, result)

    agent.include(proto, publish_manifest=True)
    connect_on_startup(agent, seed, key, NAME, ABOUT, README)
    print(f"{NAME} may only call: " + ", ".join(f"{m} {p}" for m, p in sorted(CALLS | REPLY_CALLS)))
    print(f"{NAME} address: {agent.address}; answers only Grid Desk ({desk or 'not configured: set FETCH_GRID_DESK_SEED'})")
    agent.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
