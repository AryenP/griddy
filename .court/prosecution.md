# Prosecution: Brownout fails as described

## Charges
1. The demo's physical effect is a few tens of watts on a ~100 W box, which a judge reads as a toy, not evidence of usefulness.
2. The core mechanism (clock lock plus concurrency cap) is generic throttling, and the "better than uniform throttling" claim rests on a hand-built three-job scenario.
3. The live demo has too many failure points for 3-4 minutes: phone, approval loop, 1 Hz meter, lamp step, LLM planning latency.
4. The lamp step (step 4) cannot be shown "within seconds" with a ~1 Hz plug meter plus a control loop, and may look like nothing happened.
5. Customer understanding is secondhand: regulation and press, with no operator conversation yet.
6. Emerald AI and Google already do this at scale, so novelty and production path are weak against a team that shows a real integration.
7. The agent layer adds little judges can see as necessary: the LLM is deliberately kept off the knobs, so the "agent" is a form-filling negotiator.
8. Production path is asserted (Teams, OpenADR, Foundry) rather than demonstrated, and the claims outrun a solo 36-hour build.

## Argument

**1. Toy scale.** The builder admits it. A 30% cut of ~100 W is ~30 W, about a bright bulb. Judges who deploy agents into enterprises think in MW, SLAs, and contracts. The demo proves a control loop works on one box; it does not prove the problem is solved or that savings scale. No credible extrapolation is possible from one GB10 to a campus with heterogeneous racks, cooling, and UPS behavior (speculation: judges will ask exactly this).

**2. Baseline is self-authored.** The comparison to "uniform throttling" is a strawman the builder chose. Real operators already prioritize workloads; Emerald's published results are at cluster scale against real baselines. A comparison on three toy jobs, with training that checkpoints trivially, shows the builder's design beats the builder's baseline. An experienced FDE will notice.

**3. Fragility.** The script depends on a judge's phone reaching a web console on venue Wi-Fi (hackathon networks are notoriously bad; general knowledge), a live LLM call for planning and read-back, a push buzz, an approval, a re-plan, a meter, and a lamp. One slip eats a 4-minute slot. Sim mode is a fallback, but a sim fallback in a "real world" challenge undercuts the end-to-end criterion.

**4. Meter and lamp.** The brief says plug meters update ~1 Hz. Smoothing, loop delay, and clock-lock settling make "tightens within seconds" marginal. A lamp adds ~10-60 W to a ~100 W baseline, but only if it is on the same metered strip; the compensation will be a few watts of GPU clocks, possibly inside noise. Risk: the judge watches a number wobble and cannot tell cause from effect.

**5. Customer understanding.** The brief concedes the evidence is Texas docket, PJM, FERC, and press. That is market knowledge, not customer understanding. Microsoft FDEs talk to customers daily and can tell the difference between "regulation exists" and "operators told me this is their pain." Planned Saturday chats help only if they land in the pitch.

**6. Competition.** Emerald AI (Nvidia-backed, $24.5M seed), Google's demand-response deals, and the Sept 2026 alliance mean the judge may know the space better than the builder. "We do the agent layer" invites "why does the agent layer need an LLM?" A stronger team (speculation) shows a Microsoft-native stack end to end: Foundry agent, Entra agent identity, Teams approval, real audit logs, on Azure, even if smaller in physical scope.

**7. Agent value.** Non-negotiable #1 makes the LLM a planner and narrator. The deterministic controller does the work. Priorities, deadlines, and permissions are structured inputs, so a constraint solver would do the same plan. The judge may conclude the LLM is decoration, which is weak for an agent-focused judge.

**8. Production gap.** OpenADR 3.1 intake, Slack standing in for Teams, no multi-tenant story, no integration with Kubernetes/Slurm schedulers, no failure handling when the controller loses the meter. Microsoft's "least privilege" guidance is cited, but the prototype's agent identity, allowlist, and audit are likely thin or simulated.

## Weakest criterion
**Path from prototype to production (3)**, with **measurable usefulness (2)** close behind. Path to production: the prototype is a single box with a custom proxy and nvidia-smi clocks; production means Kubernetes/Slurm schedulers, multi-vendor GPUs, facility-level metering, contractual and safety review, and Microsoft-native identity and approvals, none of which is built. Teams is "documented, not built." Measurable usefulness is limited to tens of watts and a self-designed baseline. Customer understanding (1) is third weakest, but is fixable if Saturday conversations produce a concrete quote or constraint.
