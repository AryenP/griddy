# Griddy: the judge demo (one judge, ~4 minutes, one Mac, no slides)

## On the table
- The Mac with the dashboard full-screen, lid open, on its charger. A phone (or the judge's) on the operator
  and owner pages via QR (`make qr`). QR card for the chat page.
- Wired or travel-router network; the grid feeds need internet. If the feed drops, the dashboard shows "stale" and
  the plan is marked "on last known data"; say it.
- Said once, early: nothing here is simulated. Every price, watt and dollar about this Mac (and any laptop that
  joined) is live or measured, with its source and age; the emergencies we replay are the grid operators' recorded
  data with the official report's page on every line; grid-scale numbers say "estimate".
- Before the judge arrives: `make preflight`, `make demo`, and give training work (a deadline) so the Mac has
  something to shed when the cut comes.

## Script
0:00 Open. Point at the header: *"When the grid runs short, the plan for AI data centers is diesel generators.
This is the alternative."* Under it, the quote from the Microsoft FDE or operator collected Saturday.

0:15 The grid and the plan. Let them pick the objective (cost, carbon, balanced: keys 1, 2, 3). The grid is
CAISO, live (San Francisco's load pays PG&E's price). The 24-hour dispatch map repaints against the live price curve: training in the
cheap slots, batch where it is cheapest, chat always on. Click any slot (or use the arrow keys): the inspector
says what runs there and the solver's reason, with the slot's price and cap.

0:45 They use the service. Chat from their phone; the reply streams; time to first token on screen against the
1 s SLA. The load trace shows the Mac's measured watts live, with $/h and gCO2/h at the live price and mix.

1:10 They are the utility. On the operator page: "grid alert, I need 30% off for the next twenty minutes."
The agent reads it back: target watts, what will move, what needs approval. Nothing moves before the read-back.

1:30 They are the owner. Their phone shows the training owner's request. Ask them to refuse in words: "no,
this has to finish by 9 AM Monday." The plan holds the utility's cap and asks the operator; they decide. On the
dashboard: the red cap line appears, measured watts drop under it, "Within the cap", the seconds it took, and
"N% below the 60 s before the cap" (the number that reads the same at 50 MW). Let their last chat reply finish
before the 1:10 request: a streaming reply draws most of the GPU, so while chat is busy this Mac cannot get under
a 30 % cut, and by design chat keeps full speed and the operator is asked instead (DECISIONS 10:00, 14:16). If they
chat during the cut, show that: "chat is serving 1 request at full speed (slowing chat is the operator's call)".

2:20 An emergency, replayed live (the judge picks). Three cards: Winter Storm Uri in San Francisco (simulated),
California's rotating outages (2020), California's record heat wave (2022). They press Replay it live; the hours
are fetched live from the EIA's API right then (the footer says so) and reach the software one hour at a time, never
a later one. Uri says "simulated" wherever it shows: California's own recorded hours from those two days, with the
share of what it needed that Texas could serve, hour by hour, so the gap fills red through the night. The warnings
issued days before fire first and the Mac shifts its work; at 1:20 a.m., Uri's EEA 3 moment, the real dispatcher
cuts the Mac deeper, measured. Read Without Griddy / With Griddy: about 135,000 San Franciscans lose power
(simulated, at Texas's own rate, 4.5 million of 29.1 million) against the San Franciscans kept on by data centers
cutting like this Mac, per 1 GW of them (a stated unit, on screen). The two California events are real, every line
with its report's page.

(If asked "where are the data centers?") Click either data center: the camera flies into San Francisco's four, as
OpenStreetMap maps them, by address (365 Main, 360 Spear, 630 3rd, 200 Paul), each joined to its nearest PG&E
substation. Power pulses along each join at this Mac's measured watts, which stand in for each; under a cap it turns
mint and flows back out. Hover one for its footprint. Back returns.

(If asked "what if X fails?") Break it. Click any plant, the substation or the city, or press Break a part and
type it ("an ice storm freezes half the gas plants"). Read the reading aloud ("the gas fleet loses 50 %: -X GW of its
real Y GW now"), confirm, and point at Without Griddy / With Griddy and the "Griddy acts" card. Click the city to open
its map: real hospitals stay lit, dark blocks rotate, mint blocks are the ones Griddy's freed power relights.

3:10 Receipts. Open the proof page: the same utility call measured under three policies (DECISIONS 09:46):
ignore the call 20.85 W and 0 % of seconds under the cap; pause everything 0.80 W, 99 %, 19 training steps;
Griddy 14.34 W, 93 %, compliant in 12 s, 1575 steps (over the same 315 s), about 83 times the work of pausing everything. Then one
decision's trace (Application Insights, or `/api/trace` while Azure lags).

3:45 Close. "This is tens of watts on a laptop. The feeds, the solver, the approvals and the audit trail are
the same at 50 megawatts, and the request came in the format utilities already send. Built on Microsoft Agent
Framework; in production the agent gets an Entra Agent ID and approvals land in Teams."

Optional if time remains: Impossible ask. "Ask for 90%." The solver shows the floor with chat protected and
asks the operator to approve going over the cap; the ask says what a no would do to chat (it may then be degraded,
never without that answer). The shortfall is logged.

## Failure drills (rehearse Saturday evening)
- Grid feed down: stale badge, plan on last known data, say it.
- Ollama dies: chat page error; say it; the rest continues.
- LLM API down: solver and controller continue; "agent offline" badge; nothing pretends to be the agent.
- Solver infeasible: it shows the minimal relaxation, never a blank.
- Judge types something odd: the agent asks one clarifying question; let it.
- The replay says "nothing to shed": nothing of ours was running; give training a deadline and replay.
- Lid closed: the Mac sleeps whatever keep-awake does (DECISIONS 08:00); keep it open.

## Prize opt-ins on Devpost
Microsoft Challenge · Most Technically Advanced · Best Planet-First · Hyphenate (video) · Fetch only if the
three-agent ASI:One flow was built · nothing else. (Not Best Solo Hack: four people built this.)
