# Demo video script (≤ 3 minutes; Hyphenate requires one)

Record on the demo Mac with live data: screen capture of the dashboard plus the phone. Open on the
refusal, because that is the moment no other entry has. Every number on screen is live or measured; if
a feed is stale on the day, leave the "stale" badge in the shot and say it.

| Time | Picture | Voice |
|---|---|---|
| 0:00 | Owner's phone: the request to pause training, with how many minutes the Monday 9 AM deadline would slip. Owner types "No, this has to finish by 9 AM Monday." | "The grid just asked this machine for 30 % less power. The training job's owner said no." |
| 0:15 | Dashboard: the deadline turns hard; watts stay under the cap on the powermetrics chart (the plan holds the cap while the operator decides); the operator's phone gets the solver's own sentence, "keeping every deadline, power goes over the cap by up to N W in N slots from HH:MM … the owner refused because …". Operator approves; only then do the watts rise. | "So it re-planned around that answer. The solver, not the language model, worked out the trade, and nothing went over the utility's limit until a person approved it." |
| 0:40 | Header: the diesel line, then the operator quote. | "During Winter Storm Fern the answer for data centers was 35 gigawatts of diesel. Brownout is the other answer." |
| 0:55 | Live CAISO price with timestamp and age; 24-h price and carbon curves with the schedule painted on. | "It reads the real grid, live, and schedules every job over the next day: training in the cheap hours, chat always on." |
| 1:15 | Switch ISO to ERCOT or objective to carbon; schedule repaints; the Mac follows the new slot. | "Change the grid or the goal, and the plan and the machine follow." |
| 1:35 | Utility types "we need 30 % off for 20 minutes"; agent reads back target watts, plan, who must approve. | "Utilities can send OpenADR or plain words. The agent reads it back before anything moves." |
| 1:55 | "Ask for 90 %": the operator message gives the floor with chat protected ("the lowest the plan goes while the cap holds is N W"); shortfall logged. | "When the ask is impossible it says so, with the number, instead of pretending." |
| 2:10 | `make report`: baseline W, event W, % reduction, time-to-compliance, chat time-to-first-token p95 against the 1.0 s SLA, approvals with names and times. | "Receipts come from the timeline only: measured watts, the live price, the live fuel mix." |
| 2:30 | `make compare` (docs/evidence/): dispatched vs dispatcher off under the same cap: 0.68 W vs 18.32 W mean, 99 % vs 0 % of seconds under the cap, compliance in 5 s, deadline still met; then the same against "pause everything" (evidence3). | "Same jobs, same live grid, same request: under the cap in five seconds, and the training still makes its deadline." |
| 2:45 | Application Insights: the trace of the refusal decision. | "Every decision is a trace in Azure Application Insights: the audit log." |
| 2:55 | Dashboard wide shot. | "A few watts on a laptop. The same loop at fifty megawatts." |
