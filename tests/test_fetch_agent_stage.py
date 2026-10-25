"""POST /request with "source": "fetch" (team/1-aryen.md "Fetch three-agent support"): a cut asked over Fetch.ai is
staged for the operator and never applied by the call; the operator's plain yes applies it from that moment, a no is
logged as a refusal. TEST FIXTURES: the agent-bridge rig from tests/test_api_agent.py (agent offline, intake by rule,
time moved by monkeypatch) and, end to end, machine 2's Facility logic (fetch_agents/facility.py) calling the real
router over HTTP. uagents is not installed here, so its messages are built on pydantic, as tests/test_fetch_three.py does."""
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

import controller.execute as ex
from api import access
from api.agent_bridge import CAP_JOB
from api.routes import make_router
from core.timeline import Timeline
from fetch_agents import facility, grid_desk
from fetch_agents.common import Loopback, models
from tests.test_api_agent import rig  # noqa: F401  (the fixture)
from tests.test_dispatcher import signal

M = models(BaseModel)
TEXT = "Grid request: 30% off for the next 20 minutes."     # facility.request_text's words for 30% / 20 min
WHO = "Grid Desk (Fetch.ai) (console)"


async def test_a_fetch_request_waits_for_the_operator_and_changes_nothing(rig):
    e, agent, tl, _ = rig
    await e.on_signal(signal([50.0] * 96))
    before = e.schedule
    result, req, preview = await agent.stage(TEXT, WHO)
    assert result.kind == "cap_event" and not result.llm_used
    assert (req.status, req.job_id, req.owner, req.asked_by, req.run_id) == ("pending", CAP_JOB, "ops", WHO, "a")
    assert req.cap_event.target_w == pytest.approx(14.0) and req.cap_event.duration_s == 1200   # 30% off 20 W, measured
    assert "Grid Desk on ASI:One" in req.message and result.readback in req.message
    assert preview is not None and any(c == pytest.approx(14.0) for c in preview.caps_w if c is not None)
    assert e.events == [] and e.schedule is before                    # nothing applied, nothing re-planned
    assert e.needs_approval == [req.id]                               # the next plan carries it
    kinds = [ev.kind for ev in Timeline.read(tl.path)]
    assert "event" not in kinds and "approval" in kinds
    await e.on_signal(signal([60.0] * 96))                            # a re-solve does not expire someone's ask
    assert agent.approvals[req.id].status == "pending"


async def test_the_operators_plain_yes_applies_the_cut_from_that_moment(rig):
    e, agent, tl, _ = rig
    await e.on_signal(signal([50.0] * 96))
    _, req, _ = await agent.stage(TEXT, WHO)
    for text in ("sure, if it is quick", "cut 10% instead"):          # anything but a plain yes or no asks again
        decision, sched = await agent.reply(req.id, text, "ops phone", acting_as="ops")
        assert decision.decision == "unclear" and not decision.llm_used and sched is None and e.events == [], text
    decision, sched = await agent.reply(req.id, "yes", "ops phone", acting_as="ops")
    a = agent.approvals[req.id]
    assert decision.decision == "approve" and (a.status, a.who, a.reply, a.run_id) == ("approved", "ops phone", "yes", "a")
    assert [ev.id for ev in e.events] == [a.cap_event.id] and e.events[0].target_w == pytest.approx(14.0)
    assert a.cap_event.start.timestamp() == pytest.approx(ex.time.time(), abs=1)   # from the yes, not from the ask
    assert sched is e.schedule and any(c == pytest.approx(14.0) for c in sched.caps_w if c is not None)
    assert [ev.kind for ev in Timeline.read(tl.path)].count("event") == 1


async def test_a_no_is_logged_as_a_refusal_and_nothing_is_applied(rig):
    e, agent, tl, _ = rig
    await e.on_signal(signal([50.0] * 96))
    _, req, _ = await agent.stage(TEXT, WHO)
    decision, sched = await agent.reply(req.id, "no, the training run matters more tonight", "ops phone", acting_as="ops")
    assert decision.decision == "refuse" and sched is None and e.events == []
    assert agent.approvals[req.id].status == "refused"
    notes = [ev.data.get("msg", "") for ev in Timeline.read(tl.path) if ev.kind == "note"]
    assert any("refused the cut" in n and "training run matters more" in n for n in notes)


async def test_a_staged_request_never_stands_in_for_the_solvers_own_ask(rig):
    """The operator's over-cap question (job_id power_cap too) is still asked while a Fetch request is pending."""
    e, agent, _, _ = rig
    await e.on_signal(signal([50.0] * 96))
    _, staged, _ = await agent.stage(TEXT, WHO)
    await agent.request("grid alert, I need 50% off for the next 2 hours", "judge")
    await agent.reply(agent.pending(owner="ml")[0].id, "no, this has to finish by 9 AM Monday", "owner")
    ops = [a for a in agent.pending(owner="ops") if a.job_id == CAP_JOB]
    assert {a.id for a in ops} >= {staged.id} and len(ops) == 2
    assert next(a for a in ops if a.id != staged.id).cap_event is None and staged.cap_event is not None


async def test_facility_and_the_real_route_agree_on_the_staged_contract(rig):
    """Machine 2's Facility stages a cut through the real POST /request, offers the solver's plan, and reports the
    operator's yes with the cap as applied: the contract both sides were written against."""
    e, agent, tl, _ = rig
    await e.on_signal(signal([50.0] * 96))

    class Runtime:                                                    # what the two routes read from the runtime
        def __init__(self):
            self.agent, self.tl, self.executor = agent, tl, e

    app = FastAPI()
    app.include_router(make_router(Runtime()))
    with TestClient(app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50123)) as http:
        def forward(r: httpx.Request) -> httpx.Response:            # Facility's own httpx client, answered by the app
            out = http.request(r.method, r.url.path, params=r.url.params, content=r.content, headers=r.headers)
            return httpx.Response(out.status_code, content=out.content, headers=out.headers)

        fac = facility.Facility(Loopback("http://127.0.0.1:8080", facility.CALLS, httpx.MockTransport(forward)), M,
                                "agent1qdesk")
        req = M.CurtailmentRequest(id="cut-0001", target_pct=30.0, duration_s=1200, requested_by=grid_desk.NAME)
        assert facility.request_text(req) == TEXT
        offer = fac.on_request("agent1qdesk", req)
        assert offer.status == "offered" and offer.needs_approval and offer.approval_id, offer
        assert agent.approvals[offer.approval_id].status == "pending" and e.events == []
        assert fac.check("cut-0001") is None                          # still waiting for the operator
        await agent.reply(offer.approval_id, "yes", "ops phone", acting_as="ops")
        out = fac.check("cut-0001")
    assert out.accepted and out.status == "approved" and out.who == "ops phone" and out.words == "yes"
    assert (out.cap_id, out.run_id) == (e.events[0].id, "a") and out.target_w == pytest.approx(14.0)


def test_a_fetch_request_is_taken_from_loopback_only(monkeypatch):
    """A joined phone on the venue network cannot stage (or apply) a Fetch request; other sources are unchanged."""
    monkeypatch.setattr(access.settings, "operator_token", "t")

    class Agent:
        calls = []

        async def stage(self, text, who):
            self.calls.append(text)

    class Runtime:
        agent = Agent()

    app = FastAPI()
    app.include_router(make_router(Runtime()))
    phone = TestClient(app, headers={access.HEADER: "t"})            # the test client is not this machine
    r = phone.post("/request", json={"text": TEXT, "who": "x", "source": "fetch"})
    assert r.status_code == 403 and "loopback" in r.json()["detail"] and Agent.calls == []
    assert phone.post("/request", json={"text": TEXT, "source": "email"}).status_code == 422
