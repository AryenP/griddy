# Defense: Brownout

## Thesis
Brownout wins because it is the one project in the room built the way a forward-deployed engineer would build an agent for a real customer: the LLM negotiates and explains, a deterministic controller acts, an independent wall meter proves the result, and the judge personally experiences every role in the workflow in four minutes. The scale is a toy, but the control architecture, the audit trail and the honest "can't do 90%" answer are exactly what production looks like.

## Argument (per Microsoft criterion)

**1. Customer understanding.** The problem is stated in one sentence and has hard, dated stakes: Texas PUCT Docket 59220 forces uncompensated full curtailment in 30 minutes, and PJM curtails new large loads first. The brief models the customer's real constraints, not a generic "save energy" pitch: workloads differ in priority, deadlines and interruption permission, and job owners must consent. The admitted gap (no operator interview) is partly closed by the planned Saturday conversations with Microsoft FDEs, who are the nearest thing to the customer in the building. The shortfall negotiation shows an understanding that operators fear silent failure more than partial compliance.

**2. Measurable usefulness.** Most hackathon demos assert value; this one measures it. Two independent power numbers (NVML and wall meter), plus a head-to-head against uniform throttling on watts under cap, p95 chat latency, work completed and checkpoint recovery. The judge watches a physical meter drop while their own phone chat stays fast. The lamp step is a live, unrehearsable disturbance that tests closed-loop control, which is hard to fake.

**3. Prototype to production.** The design already has the seams: OpenADR 3.1 as the input standard, a pluggable owner channel (web console now, Slack next, Teams as the documented production adapter), an LLM client abstraction that runs on Claude or Foundry, and a `--mode sim` that runs everything without hardware. Tests gate commits. Every run writes a timeline from which the compliance report is generated, which is the artifact a utility or auditor would actually want. (Speculation: an FDE will value the explicit "what changes at 100 MW" list more than a bigger demo.)

**4. Responsible design.** This maps almost line for line onto Microsoft's July 2026 least-privilege guidance: the model has no power-knob access, tool calls pass through a deterministic controller (the Foundry Agent Control idea), step-up human approval is required before disruptive actions, and everything is logged. Protected SLA for chat, checkpoint-before-pause and refusal to overpromise are responsible design shown behaviorally, not claimed on a slide.

**5. End-to-end functionality.** The full loop runs: ingest request, plan, approve, actuate, verify, re-plan, report. The judge triggers each step themselves, so there is no "imagine this part works." Sim mode and a documented fallback mean a dead meter or network degrades the demo instead of ending it.

## Answers to the obvious objections

**"It's a 100 W toy."** True, and the brief says so. But the claim is about the control layer, not wattage. Judges deploying agents into enterprises know the hard part is permissions, approvals and verification, not the size of the load. Tens of watts is plenty to read on a meter and to see a lamp's effect. Most competing projects are toys too; this one is a toy of a real system.

**"Emerald AI and Google already do this."** Their existence validates the market, which is the strongest customer-understanding evidence available. The differentiator is deliberate: an agent layer with human approval, independent verification and honest shortfall negotiation. (Speculation: large incumbents are unlikely to expose those internals; a judge may find them more interesting than raw scale.)

**"GB10 power limits may not work; the meter is 1 Hz."** Clock locking is the fallback, and the CLAUDE.md rule is to adapt to the hardware rather than fight it. A 1 Hz meter with "tightens within seconds" is a claim a judge can verify by eye. Reporting the two numbers separately, and saying so when the meter is absent, is itself credibility.

**"Solo, no Teams, no operator interview."** Scope discipline is a feature: a web console that works beats a Teams integration that doesn't. The Teams path is documented, not faked. The interview gap is a real weakness, but it affects the pitch's evidence, not the demo's function, and Saturday conversations can partially fill it.

**"Four minutes is too short for six steps."** Each step is a single judge action with a visible result, and steps 4 and 5 can be trimmed live. Cutting scope rather than adding time is already the stated working rule.

**Risks I will not wave away:** a live demo depends on hardware and a phone round trip; sim fallback mitigates but does not remove that.
