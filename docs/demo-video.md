# Demo video script (≤ 3 minutes; Hyphenate requires one)

Record on the demo Mac with live data (lid open, on the charger, `make demo`, training given a deadline first):
screen capture of the dashboard plus the phone. No chat reply streaming while the cap is on: busy chat alone is above
a 30 % cut on this Mac, and chat keeps full speed by design, so the shot would be the operator ask (DECISIONS 14:16). Open on the refusal, because that is the moment no other entry
has. Every number about the Mac is live or measured; the replayed emergency is the grid operator's recorded data with
its sources on screen; nothing is simulated. If a feed is stale on the day, leave the "stale" badge in the shot and
say it.

| Time | Picture | Voice |
|---|---|---|
| 0:00 | Owner's phone: the request to pause training, with how many minutes the Monday 9 AM deadline would slip. Owner types "No, this has to finish by 9 AM Monday." | "The grid just asked this machine for 30 % less power. The training job's owner said no." |
| 0:15 | Dashboard, the load trace: the red cap line, measured watts under it, "Within the cap", the seconds it took, "N % below the 60 s before the cap". The operator's phone gets the solver's own sentence about going over the cap; nothing goes over until a person approves. | "So it re-planned around that answer. The solver, not the language model, worked out the trade, and nothing went over the utility's limit until a person approved it." |
| 0:40 | Header: the diesel line, then the operator quote. | "During Winter Storm Fern the answer for data centers was 35 gigawatts of diesel. Brownout is the other answer." |
| 0:55 | The 24-hour dispatch map on the live CAISO price (timestamp and age); click a slot, the inspector gives the solver's reason. | "It reads the real grid, live, and plans every job over the next day: training in the cheap hours, chat always on." |
| 1:15 | Switch the objective (key 2) or the grid to ERCOT; the map repaints; the Mac follows the new slot. | "Change the grid or the goal, and the plan and the machine follow." |
| 1:30 | Operator page: "we need 30 % off for 20 minutes"; the agent reads back target watts, plan, who must approve. | "Utilities can send OpenADR or plain words. The agent reads it back before anything moves." |
| 1:45 | Replay Winter Storm Uri: Texas's own forecast against the demand it could serve, the gap growing red; ERCOT's warnings days before, then EEA 3 at 1:20 a.m. reaching the Mac; the Mac's measured drop; "4.5 million people lost power, 210 died" with the report's page. | "This is February 2021, from the grid operator's own data. ERCOT warned days ahead; our software acts on the warning, and when the emergency comes it cuts in seconds. Every data center in Texas that did what this Mac just did would have freed this much power, from the event's own numbers." |
| 2:15 | Proof page (docs/evidence/, DECISIONS 09:46): ignore the call 20.85 W, 0 % under the cap; pause everything 0.80 W, 99 %, 19 training steps; Brownout 14.34 W, 93 %, compliant in 12 s, 1575 steps (same 315 s). | "Measured, same call, three policies: pausing everything holds the cap and stops the work; Brownout holds it 93 % of the time and keeps training, about 83 times as much." |
| 2:40 | Application Insights (or /api/trace): the trace of the refusal decision. | "Every decision is a trace in Azure Application Insights: the audit log." |
| 2:55 | Dashboard wide shot. | "Tens of watts on a laptop. The same loop at fifty megawatts." |
