"""Connects machine 4's agent (agent/*) to the runtime. The agent only returns data (IntakeResult,
ApprovalRequest, OwnerDecision, Explanation); this module decides what the runtime does with it,
always through the executor's public methods, never through a knob.

- Shortfalls in a new schedule become ApprovalRequests: a deadline slip goes to the job's owner
  (message drafted by the negotiator from the solver's facts); going over a cap goes to the operator
  (the solver's own sentence).
- Replies are parsed by the negotiator and applied as solver inputs: approve -> the slipped finish
  becomes the deadline; new_deadline -> that deadline; refuse -> the deadline turns hard and the
  solver bends the cap instead, which then needs the operator.
- Every new schedule gets a two-sentence explanation (explainer; falls back to the solver's facts).
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from agent import explainer, intake, negotiator
from agent.llm import get_llm
from controller.execute import Executor
from core.config import isos as ISOS_CFG
from core.timeline import Timeline
from agent.negotiator import CAP_JOB
from core.types import ApprovalRequest, Explanation, IntakeResult, Schedule


class AgentBridge:
    def __init__(self, tl: Timeline, executor: Executor):
        self.tl, self.ex = tl, executor
        self.llm = get_llm()
        self.approvals: dict[str, ApprovalRequest] = {}
        self.refused: dict[str, str] = {}        # job id -> the owner's reason for refusing a slip
        self.cap_refused: set[frozenset[str]] = set()   # caps the operator refused to go over: don't re-ask
        self.explanation: Explanation | None = None
        self.snapshot = None                     # set by the Runtime: () -> the /api/state dict
        executor.schedule_listeners.append(self.on_schedule)

    @property
    def status(self) -> str:
        return "online" if self.llm.available else "offline"

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        iso = self.ex.signal.iso if self.ex.signal else None
        tz = ISOS_CFG["isos"].get(iso, {}).get("timezone", "UTC") if iso else "UTC"
        return datetime.fromtimestamp(time.time(), ZoneInfo(tz))   # the executor's clock

    def _log(self, req: ApprovalRequest, **extra) -> None:
        self.tl.log("approval", **req.model_dump(mode="json"), **extra)
        self.ex.needs_approval = [a.id for a in self.approvals.values() if a.status == "pending"]

    def pending(self, owner: str | None = None, status: str | None = "pending") -> list[ApprovalRequest]:
        return [a for a in self.approvals.values()
                if (owner is None or a.owner == owner) and (status is None or a.status == status)]

    def _open_for(self, job_id: str) -> ApprovalRequest | None:
        return next((a for a in self.approvals.values() if a.job_id == job_id and a.status == "pending"), None)

    # ------------------------------------------------------------------ schedules
    async def on_schedule(self, sched: Schedule) -> None:
        """Ask the owner first: a deadline that may slip is the cheaper option. Only when no deadline
        can slip (refused, or none involved) does a cap shortfall go to the operator."""
        jobs = {j.id: j for j in self.ex.jobs()}
        live_jobs = set()
        slips = [sf for sf in sched.shortfalls
                 if sf.kind == "deadline" and sf.job_id in jobs and sf.job_id not in self.ex.hard_deadlines]
        for sf in slips:
            live_jobs.add(sf.job_id)
            if not self._open_for(sf.job_id):
                req = await negotiator.draft_ask(sf, jobs[sf.job_id], self.llm)
                self.approvals[req.id] = req
                self._log(req, schedule_id=sched.id)
        cap = next((sf for sf in sched.shortfalls if sf.kind == "cap"), None)
        key = self.ex.cap_key()
        if cap and not slips and key not in self.ex.cap_overrides and key not in self.cap_refused:
            live_jobs.add(CAP_JOB)
            if not self._open_for(CAP_JOB):
                req = await negotiator.draft_operator_ask(sched.shortfalls, sched, self.llm, self.ex.policy.operator,
                                                          refused=dict(self.refused))
                self.approvals[req.id] = req
                self._log(req, schedule_id=sched.id)
        for a in self.pending():                 # the solver no longer needs these: expire them
            if a.job_id not in live_jobs:
                a.status = "expired"
                self._log(a, schedule_id=sched.id, why="the new schedule no longer needs this approval")
        if self.ex.signal is not None:
            self.explanation = await explainer.explain(sched, self.ex.signal, self.llm)
            self.tl.log("note", schedule_id=sched.id, explanation=self.explanation.model_dump(mode="json"))

    # ------------------------------------------------------------------ replies
    async def reply(self, request_id: str, text: str, who: str):
        req = self.approvals.get(request_id)
        if req is None:
            raise KeyError(request_id)
        if req.status != "pending":
            raise ValueError(f"request {request_id} is {req.status}")
        decision = await negotiator.parse_reply(req, text, self.llm, self._now())
        self.tl.log("approval", request_id=req.id, who=who, decision=decision.model_dump(mode="json"))
        sched = None
        if decision.decision == "unclear":
            return decision, None
        if req.job_id == CAP_JOB:
            if decision.decision == "approve":
                req.status = "approved"
                sched = await self.ex.approve_over_cap(who)          # only now may the plan exceed the cap
            else:
                req.status = "refused"                               # the cap keeps holding; deadlines slip
                self.cap_refused.add(self.ex.cap_key())
        elif decision.decision == "approve":
            req.status = "approved"
            miss = next((m for m in (self.ex.schedule.deadline_misses if self.ex.schedule else [])
                         if m.job_id == req.job_id), None)
            if miss and miss.finishes_at:
                sched = await self.ex.set_job(req.job_id, deadline=miss.finishes_at)
        elif decision.decision == "new_deadline":
            req.status = "countered"
            sched = await self.ex.set_job(req.job_id, deadline=decision.new_deadline)
        else:
            req.status = "refused"
            self.refused[req.job_id] = decision.reason
            sched = await self.ex.keep_deadline(req.job_id, decision.reason)
        self._log(req, who=who, decided_t=time.time())
        return decision, sched

    # ------------------------------------------------------------------ operator Q&A
    async def ask(self, question: str) -> Explanation:
        state = self.snapshot() if self.snapshot else {}
        result = await explainer.answer(question, state, self.llm)
        self.tl.log("note", ask=question, answer=result.model_dump(mode="json"))
        return result

    # ------------------------------------------------------------------ intake
    def _context(self) -> dict:
        return {"now": self._now().isoformat(), "baseline_w": self.ex.baseline_w(),
                "jobs": [j.model_dump(mode="json") for j in self.ex.jobs()],
                "policy": self.ex.policy.model_dump(mode="json")}

    async def _apply(self, result: IntakeResult, who: str):
        self.tl.log("intake", intake=result.model_dump(mode="json"), who=who)   # a parsed request, not a cap
        if result.kind == "cap_event" and result.cap_event:
            return await self.ex.add_event(result.cap_event)
        if result.kind == "policy" and result.policy:
            changes = result.policy.model_dump(exclude_none=True)
            return await self.ex.set_policy(**changes) if changes else None
        return None

    async def request(self, text: str, who: str):
        result = await intake.parse_request(text, self.llm, self._context())
        return result, await self._apply(result, who)

    async def openadr(self, event: dict, who: str):
        result = intake.parse_openadr(event)
        return result, await self._apply(result, who)
