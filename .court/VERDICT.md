# VERDICT: Brownout on trial (quick mode, 6 jurors, 23 Oct 2026 8:20 PM)

Charge: "This idea, as described, fails to win the Microsoft Challenge Grand Prize."

GUILTY, 4 to 2. The idea as written loses; the idea with the conditions below wins the two swing jurors and likely two more.

| Juror | Vote | One-line reason |
|---|---|---|
| Microsoft FDE | GUILTY | Production path is slides and seams; usefulness measured against a self-authored baseline on a toy box; customer understanding secondhand. |
| Data-center ops director | GUILTY | One-box toy; lamp step likely invisible on a 1 Hz meter; evidence is dockets and press, not an operator. |
| Hackathon veteran (30 events) | NOT GUILTY | Judge-as-participant loop with a physical meter and honest shortfall negotiation sticks with a tired judge; fragile parts have concrete fixes. |
| Megawatt-flexibility founder | GUILTY | Against a judge who knows Emerald it reads as a well-built toy; the LLM only parses text a solver could handle. |
| Utility DR program manager | GUILTY | A 30 W swing with a self-picked baseline proves the loop closes, not that it works for a real program. |
| Sceptical CS student | NOT GUILTY | The judge runs the whole loop from plain English to refusal to "can't do 90%"; jealous-worthy despite the toy scale. |

## Charges that stuck
1. Customer understanding is secondhand. Five of six jurors named this. Regulation and press are context, not a customer.
2. Production path is asserted, not shown. Teams/OpenADR/Foundry as roadmap bullets convince nobody who deploys for a living.
3. Usefulness is scored against a baseline the builder wrote. Judges who verify curtailment want a measured baseline, a measured response time and a verified shed.
4. The lamp step may show nothing on a 1 Hz plug meter inside a 3 to 4 minute demo.
5. The LLM looks optional. If the agent only parses a sentence a regex could parse, the "agent" is decoration.

## What the defense got right
- Responsible design (deterministic controller, LLM never on the knobs, step-up approval, audit log) was conceded by the prosecution and praised by every juror.
- The judge-as-participant demo and the explicit shortfall answer are the memorable parts; keep them exactly.
- Candour about scale blunts the "toy" objection; keep saying "100 W box, same control loop as 100 MW".

## Conditions for acquittal (do these, in this order)
1. Opening slide = an operator or FDE quote. Saturday morning, ask three Microsoft FDEs at the 10 AM workshop and anyone at the a16z/Annapurna tables: "Which workloads would you never let an agent pause, and who has to approve?" Put the best answer, attributed, on slide one. Encode their answer as the default `permissions.yaml`.
2. Show one Microsoft-native thing running live, not described. Minimum: agent built on Microsoft Agent Framework with every action traced to Application Insights, and the audit log on screen during the demo. Stretch: deploy the agent to Foundry Hosted Agents and have the demo call it there. Say "Entra Agent ID and Teams approvals in production" once, with the Jul 2026 least-privilege post as the citation.
3. Measure like a utility does. Before the event: a 5-minute baseline window at normal load (the DR "baseline"). During: the cap. After: compliance = average metered reduction vs baseline over the event window, plus time-to-compliance in seconds on the wall meter. Print all three on the report and on the dashboard. The uniform-throttle comparison stays, but as the second chart, not the headline.
4. Rehearse the lamp step with a stopwatch. If time-to-tighten on the wall meter is not under ~5 s reliably, cut the lamp from the live script and show it in the video instead. Never improvise it.
5. Give the LLM a job only an LLM can do. The request must be messy (an email with two constraints and a typo; a voice message), the negotiation must be free-form (the owner replies in words, not buttons only), and the shortfall explanation must be written for a human operator. Keep "Approve/Refuse" buttons as fallback, but the demo uses the text reply.
6. Stability over features. Local hotspot/router for the demo (venue Wi-Fi is already failing; note the venue bans hotspots inside, so use wired or a travel router on the table and check the rule), sim fallback wired to one keypress, two full rehearsals Saturday evening.

Record: `.court/brief.md`, `prosecution.md`, `defense.md`, `prosecution_rebuttal.md`, `defense_rebuttal.md`.
