# Microsoft Challenge criteria and the evidence for each

Every number below is quoted from a dated line in `DECISIONS.md` (cited as D hh:mm, all 2026-10-23/24 PT) or
from `RESEARCH.md` (R). Anything not measured yet says to be measured. Each section lists its gaps.

## 1. Customer understanding
| Evidence | Where |
|---|---|
| The request format a utility already sends: OpenADR 3.1 `IMPORT_CAPACITY_LIMIT`, parsed deterministically | R "The request format: OpenADR 3.x"; `agent/intake.py` `parse_openadr`; `POST /openadr/event` |
| The rules that make curtailment an obligation (PUCT 59220, PJM Board, FERC, DOE §403) and the 10 to 30 % DCFlex range | R "Why a utility can order this"; [compliance.md](compliance.md) |
| How compliance is verified in real programs (interval meter, baseline, time to compliance) and the same three numbers in our report | R "How compliance is verified"; `agent/reporter.py`; receipts on the dashboard |
| Who decides what: job owners approve deadline slips, the operator approves going over a cap | D 02:55; [customer.md](customer.md) |

Gap: no operator or FDE quote yet. The quote slot reads "to be collected at the Sat 10 AM Microsoft
workshop" ([customer.md](customer.md)).

## 2. Measurable usefulness
| Claim | Measured | Where |
|---|---|---|
| Watts follow the plan at a slot boundary with no human input | 18.5 W → 2.17 W at the 23:45:00 boundary, under a 15 W cap within ~4 s; back to 17.50 W after the cap ended | D 23:45, D 00:00, run 20261023-233727 |
| Dispatched vs dispatcher off, same scripted call (cap 30 % below the measured baseline, 300 s) | mean 21.18 W vs 1.64 W; energy 1.761 vs 0.132 Wh (−92 %); 0 % vs 99 % of seconds at or under the cap; time to compliance never vs 7 s; deadlines 1/1 both | D 03:10; `docs/evidence/compare-20261024-025349-vs-20261024-024609-baseline.md` |
| The same comparison, earlier run | 18.32 W vs 0.68 W; −96 % energy; 0 % vs 99 %; never vs 5 s | D 02:28 |
| Against the honest naive policy (pause everything) and ignoring the call, 326 s | ignore: 22.32 W, 0 % under the cap, 5568 train steps; pause all: 2.09 W, 97 %, 17 steps; Brownout: 13.96 W, 69 %, 1562 steps, compliant in 10 s | D 03:55 (first pass; see the gap below) |
| Chat stays usable during a cap | time-to-first-token p95 worst 0.29 s idle / 0.24 s with training (SLA 1.0 s); 3 live users: first token ≤ 0.17 s | D 00:22, D 01:50 |
| Live prices are what the ISO published | timeline $48.67721 = OASIS raw $48.67721 for SP15 23:15 PDT | D 23:15 (M1 evidence) |

Gaps:
- The three-policy run exposed load outside the plan: about 1.2 W on the GPU that Brownout did not start held the machine over the cap from 318 s. A fix (measured background load counted against the cap) landed after it, and the re-run is to be measured (D 03:55).
- One laptop draws from about 0.5 W idle to about 25 W per job (calibration, D 03:10). The claim is that the loop is the same at site scale, not that a laptop matters to the grid ([production.md](production.md)).

## 3. Path to production
See [production.md](production.md). The feeds, solver, approvals, timeline and OpenADR intake stay the same. The
meter becomes a revenue-grade interval meter, the owner channel becomes Teams via the Microsoft 365 Agents SDK,
each agent gets an Entra Agent ID, and an OpenADR 3.1 VTN (e.g. OpenLEADR-rs) sends the events (R).
Already running: OpenTelemetry spans per decision, exportable to Application Insights; `azd provision`
infrastructure for Application Insights (D, telemetry entry by machine 3).

Gap: the Foundry deployment and Content Safety resource are not provisioned yet (team/2-anuraag.md task 9).

## 4. Responsible design
See [responsible.md](responsible.md):
- The solver decides, the LLM words things and the controller executes. The LLM has no code path to a knob.
- Approvals gate the risky action (D 02:55).
- Invented numbers are rejected (D 15:00, the agent layer entry).
- 19 of 19 prompt injections rejected live, and 135 of 138 eval cases pass live, the judge's fault reader 14 of 14 (Sat 20:33; `docs/evidence/evals-live-20261024-2033.md`; the first live run at 02:33 passed 86 of 90).
- The offline mode keeps the plain forms working.
- Every decision is in the timeline and as a span.

Gap: four live eval misses are judgment calls, listed in the evidence file. One ("Tuesday 9" should ask AM or PM) was
fixed by a regex check (D 03:00).

## 5. End to end
`make demo` runs everything live from one terminal: the live ISO feed → CP-SAT schedule → executor on the Mac's real
workloads → powermetrics → timeline → dashboard, phone pages and receipts. `make preflight` checks it is ready.
Solver: OPTIMAL in 0.06 s on the live curve, and reproducible run to run (D 23:15 M3, D 23:50).

Gaps:
- ERCOT is verified end to end without the meter only (D 00:35). PJM needs an API key and is hidden without one (D 21:40).
- No power evidence is valid while other work runs on the demo Mac (D 01:50), so the demo Mac must be otherwise idle.
