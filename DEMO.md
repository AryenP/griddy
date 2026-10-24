# Brownout — the judge demo (one judge, ~4 minutes, one Mac, no slides)

## On the table
- The Mac with the dashboard full-screen. A phone (or the judge's) on the owner console via QR. QR card for the chat page.
- Wired or travel-router network; the grid feeds need internet. If the feed drops, the dashboard shows "stale" and the plan is marked "on last known data"; say it.
- Nothing simulated. Everything the judge sees is live ISO data or measured on this machine.

## Script
**0:00 Open.** Point at the header: *"When the grid runs short, the plan for AI data centers is diesel generators. This is the alternative."* Under it, the quote from the Microsoft FDE/operator collected Saturday. "Pick a grid."

**0:15 They pick the ISO and the policy.** CAISO, ERCOT or PJM; cost, carbon or balanced. The dashboard shows live prices (with the interval timestamp), the 24-hour price and carbon curves, and the schedule painted on top: training in the cheap overnight slots, batch in the clean midday solar, chat always on. The solver's explanation reads in two sentences.

**0:45 They use the service.** Chat from their phone; replies fast; chat p95 on screen. Measured watts, $/h and gCO2/h on screen, all live.

**1:15 They're the utility.** "Tell it what you need, in your own words." They type or dictate: "grid alert, I need 30% off for the next twenty minutes." Agent reads back: target watts, what it will do (pause training, drop batch, keep chat), what needs approval, and asks the training owner.

**1:45 They're the owner.** Their phone shows the request. Ask them to refuse in words: "no, this has to finish by 9 AM Monday." The solver re-plans with that constraint: "Keeping your deadline, I can reach 22%, not 30%, unless chat slows by ~1 s. Approve?" They decide. Watts drop; time-to-compliance counter shows seconds; chat still responds.

**2:30 They move the grid.** Switch the policy to carbon, or switch ISO to ERCOT. The schedule repaints against the new live curve; the explanation changes; the Mac follows the new current-slot plan.

**3:00 Impossible ask.** "Ask for 90%." Agent: "Floor with chat protected is N W (≈47%). Approve going dark on everything else, or accept 47%?" Shortfall logged.

**3:30 Receipts.** Release the event. Training resumes from checkpoint. The report renders: baseline W, event W, % reduction, time-to-compliance, approvals with names and times, p95 before/during. Then the comparison: dispatched vs dispatcher-off over the same window: $ and gCO2 saved, deadlines met, watts under cap. Then the audit trace (Application Insights) for one decision.

**3:50 Close.** "This is 30 watts on a laptop. The feeds, the solver, the approvals and the audit trail are the same at 50 megawatts, and the request came in the format utilities already send. Built on Microsoft Agent Framework; in production the agent gets an Entra Agent ID and approvals land in Teams."

## Failure drills (rehearse Saturday evening)
- Grid feed down → stale badge, plan on last known data, say it.
- Ollama dies → chat page error; say it; the rest continues.
- LLM API down → solver and controller continue; "agent offline" badge; nothing pretends to be the agent.
- Solver infeasible → it must show the minimal relaxation, never a blank.
- Judge types something odd → the agent asks one clarifying question; let it.

## Prize opt-ins on Devpost
Microsoft Challenge · Most Technically Advanced · Best Planet-First · Best Solo Hack if still solo · Hyphenate (video) · Fetch only if the three-agent ASI:One flow was built · nothing else.
