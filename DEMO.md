# Brownout — the judge demo (one judge, ~4 minutes, one Mac, no slides)

## On the table
- The Mac with the dashboard full-screen, lid open, on its charger. A phone (or the judge's) on the operator
  and owner pages via QR (`make qr`). QR card for the chat page.
- Wired or travel-router network; the grid feeds need internet. If the feed drops, the dashboard shows "stale" and
  the plan is marked "on last known data"; say it.
- What is real and what is not, said once, early: every price, watt and dollar about this Mac (and any laptop that
  joined) is live or measured, with its source and age. The neighbourhood power line around it is SIMULATED and
  every simulated part says so on screen (DECISIONS 05:45).
- Before the judge arrives: `make preflight`, `make demo`, and give training work (a deadline) so the Mac has
  something to shed when the cut comes.

## Script
**0:00 Open.** Point at the header: *"When the grid runs short, the plan for AI data centers is diesel generators.
This is the alternative."* Under it, the quote from the Microsoft FDE or operator collected Saturday.

**0:15 The grid and the plan.** Let them pick the objective (cost, carbon, balanced: keys 1, 2, 3) and, if they
like, the grid (CAISO or ERCOT). The 24-hour dispatch map repaints against the live price curve: training in the
cheap slots, batch where it is cheapest, chat always on. Click any slot (or use the arrow keys): the inspector
says what runs there and the solver's reason, with the slot's price and cap.

**0:45 They use the service.** Chat from their phone; the reply streams; time to first token on screen against the
1 s SLA. The load trace shows the Mac's measured watts live, with $/h and gCO2/h at the live price and mix.

**1:10 They are the utility.** On the operator page: "grid alert, I need 30% off for the next twenty minutes."
The agent reads it back: target watts, what will move, what needs approval. Nothing moves before the read-back.

**1:30 They are the owner.** Their phone shows the training owner's request. Ask them to refuse in words: "no,
this has to finish by 9 AM Monday." The plan holds the utility's cap and asks the operator; they decide. On the
dashboard: the red cap line appears, measured watts drop under it, "Within the cap", the seconds it took, and
"N% below the 60 s before the cap" (the number that reads the same at 50 MW).

**2:20 The grid around it (simulated, say so).** "Around this Mac we drew a simulated neighbourhood: homes on
today's real load forecast, a solar farm, 20 data centers, a line limit and a diesel generator." Press **Replay
the evening peak** (dashboard, or the operator page). Today's 4 PM to 9 PM plays in 90 s: the line climbs toward
its limit, the utility's cut goes to the real dispatcher, this Mac sheds for real, the simulated data centers
follow its measured response, the line stays under its limit and the diesel stays off. The panel shows the
diesel it would have burned had our sites ignored the cut.

**3:10 Receipts.** Open the proof page: the same utility call measured under three policies (DECISIONS 09:46):
ignore the call 20.85 W and 0 % of seconds under the cap; pause everything 0.80 W, 99 %, 19 training steps;
Brownout 14.34 W, 93 %, compliant in 12 s, 1575 steps, about 83 times the work of pausing everything. Then one
decision's trace (Application Insights, or `/api/trace` while Azure lags).

**3:45 Close.** "This is tens of watts on a laptop. The feeds, the solver, the approvals and the audit trail are
the same at 50 megawatts, and the request came in the format utilities already send. Built on Microsoft Agent
Framework; in production the agent gets an Entra Agent ID and approvals land in Teams."

Optional if time remains: **Impossible ask.** "Ask for 90%." The solver shows the floor with chat protected and
asks the operator to approve going over the cap; the ask says what a no would do to chat (it may then be degraded,
never without that answer). The shortfall is logged.

## Failure drills (rehearse Saturday evening)
- Grid feed down → stale badge, plan on last known data, say it.
- Ollama dies → chat page error; say it; the rest continues.
- LLM API down → solver and controller continue; "agent offline" badge; nothing pretends to be the agent.
- Solver infeasible → it shows the minimal relaxation, never a blank.
- Judge types something odd → the agent asks one clarifying question; let it.
- The neighbourhood replay says "nothing to shed" → nothing of ours was running; give training a deadline and replay.
- Lid closed → the Mac sleeps whatever keep-awake does (DECISIONS 08:00); keep it open.

## Prize opt-ins on Devpost
Microsoft Challenge · Most Technically Advanced · Best Planet-First · Hyphenate (video) · Fetch only if the
three-agent ASI:One flow was built · nothing else. (Not Best Solo Hack: four people built this.)
