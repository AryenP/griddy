# Prosecution: Brownout-Orbit

## Charges
1. **Scope doubling.** The variant adds a second hard build (a believable SAR flood-segmentation pipeline) to an already tight solo 36-hour power-control stack, so end-to-end functionality is more likely to break.
2. **Customer understanding is weaker, not stronger.** The base idea's weakness (no operator conversation) is kept, and the customer becomes a niche the builder has never spoken to, with no regulation behind it.
3. **The flood map is decoration on the power story.** The map does nothing to show the power loop works, and it moves the judge's attention from the meter and the negotiation, which were the base idea's memorable parts.
4. **The framing weakens the thesis.** An EO team is not subject to a curtailment order, so the "utility asks" premise loses its evidence and the story becomes "a team chooses to ration its own compute".
5. **Prize dilution and tooling risk.** Chasing SpaceXSI means switching to Cursor mid-hackathon, for $400 and a keyboard, while the Grand Prize is the target.
6. **Measurable usefulness gets harder to defend.** "Latency-to-first-map" is a new SLA metric the builder invents, on a model trained and tested on a small public dataset.

## Argument
The verdict on the base idea was GUILTY 4–2, and its sticking charges were secondhand customer understanding, an asserted production path, a self-authored baseline, a fragile lamp step and an optional LLM. The variant fixes none of these. It adds work on top of them.

**Time budget (my estimate, not measured).** The base idea already needs a controller, two meters, an OpenADR intake, Microsoft Agent Framework with App Insights, a negotiation flow, a phone approval path, three workloads and rehearsals. The variant adds Sen1Floods11 download and preprocessing over venue Wi-Fi (the builder flags this), choosing and training a U-Net, rendering a map on the dashboard, and wiring checkpoint/resume into a segmentation fine-tune. Any one of these can eat six hours. The VERDICT's sixth condition, "stability over features", is directly contradicted. The most likely failure is a demo where the power stack works and the map is a pre-rendered image, which a Microsoft FDE who deploys agents for a living will spot and discount.

**Customer.** The base verdict's top charge was that the customer is secondhand. In the base idea the builder could at least ask Microsoft FDEs about data-center workloads they would never pause, since FDEs plausibly meet that customer. An EO analytics team is unlikely to be anyone the judges serve (speculation). The "which workloads would you never let an agent pause" question loses its natural audience, and the first-slide quote that the verdict made condition #1 gets harder to obtain.

**Thesis.** The cited evidence (Texas PUCT 59220, PJM, Emerald AI) concerns data centers under grid orders. A small EO team under a "changing electricity budget" has no such order. The variant must either quietly keep the data-center framing, with SAR workloads as costume, or admit that the customer chose a budget. The first is a pretext, and the second removes the one-sentence problem the base idea had.

**Demo.** The base demo works because the judge does something: refuses, plugs in a lamp, asks for 90%. A flood map appearing is something the judge watches. It also invites the question the builder already anticipates (why is the urgent job power-managed?), and it burns demo seconds in a 4-minute slot where step 4's lamp is already at risk.

**Prize chase.** SpaceXSI has no track-specific criteria, requires Cursor, and pays $400. Three tracks "pulling in three directions" is the builder's own phrase. Spreading effort lowers the odds on the one prize that matters here.

## Versus the base idea
**Worse, on balance.** The one real gain is a visible output, which helps the "it's real" feeling and gives the judge something to look at. It costs more than it earns:

- Same unfixed verdict charges (customer, production path, baseline, lamp, LLM role).
- Added build risk of a second hard system, solo.
- A niche customer with no regulation behind it and no obvious FDE to interview.
- A harder one-sentence problem.
- A side prize worth $400.

If the builder insists on a visible output, a cheaper fix exists: show a live token/job-progress panel for the base idea's chat and training workloads. That delivers most of the "something happens on screen" benefit without dataset, model or customer changes. Competing against the base idea, the variant is strictly riskier with a thin upside.
