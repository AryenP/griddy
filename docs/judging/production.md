# From one Mac to a 50 MW site

The demo is one laptop: about 0.5 W idle, up to about 25 W per job (calibration, DECISIONS 03:10). What is on the table is the *control loop*: read the grid, plan every job
against it, execute, measure, prove. Facts below come from `RESEARCH.md` (R) and `DECISIONS.md` (D hh:mm).

## What stays exactly as built
| Piece | Today | At site scale |
|---|---|---|
| Grid feeds | `grid/` pulls live ISO prices, day-ahead curve, load forecast and fuel mix (CAISO, ERCOT keyless; PJM with a key), each with its age; stale feeds are labelled | same feeds, same staleness rule |
| Solver | CP-SAT over 96 × 15-min slots with deadlines, caps, SLA floors and never-pause rules; minimal relaxation when infeasible | same model; jobs become fleets/queues, power terms come from per-cluster calibration |
| Approvals | owners approve deadline slips; the operator approves going over a cap, and the running plan holds the cap until then (D 02:55) | same gate; approvals arrive in Teams instead of a phone page |
| Timeline | append-only `runs/<id>/timeline.jsonl`; reports and comparisons are computed from it only | same, shipped to durable storage |
| OpenADR intake | `parse_openadr` turns an OpenADR 3.1 `IMPORT_CAPACITY_LIMIT` event into a cap with no LLM | the same parser behind a VEN client |
| Audit | one OpenTelemetry span per agent decision; Application Insights exporter when configured (D, machine 3 telemetry) | Application Insights as the audit log |

## What changes
| Today | Production | Source |
|---|---|---|
| `powermetrics` SoC watts at 1 Hz (CPU+GPU+ANE, not a wall meter, D 22:51) | revenue-grade interval meter data (5 to 15 min) plus real-time telemetry, with performance judged against a baseline ("10-of-10" average of similar days, often same-day adjusted) | R "How compliance is verified in real programs" |
| Knobs on one machine: run/pause, concurrency, threads, GPU/CPU | the same verbs per cluster (scheduler priorities, preemption with checkpoints, power capping per node) | SPEC §6; site-specific |
| Owner/operator approvals on a phone web page | Teams via the Microsoft 365 Agents SDK (two-way messaging needs tenant admin consent or a bot in a tenant) | R "Microsoft stack" |
| One API key in `.env` | a dedicated Entra Agent ID per agent, task-scoped and time-limited access, tool allowlists, step-up human approval for high-impact actions | R "Microsoft stack" (Security Blog, 16 Jul 2026); Entra Agent ID is not self-serve for a student today |
| Utility events pasted or posted by hand | an OpenADR 3.1 VTN such as OpenLEADR-rs (Rust, 3.1, Docker Compose) sending events the VEN subscribes to | R "The request format" |
| Claude via the `anthropic` SDK | Microsoft Agent Framework over a Foundry deployment (already behind the same `agent/llm.py` interface; `get_llm()` prefers Foundry when configured) | R "Microsoft stack"; `agent/llm.py` |
| Content Safety only when configured | Azure AI Content Safety Prompt Shields on every free-text request, as the code already does when the endpoint is set | `agent/intake.py` `shield_prompt` |
| One site | many sites, each a facility agent; a utility-side agent can ask several facilities for flexibility at once | PLAN.md M7 (not built) |

## Why a site would run it
- Rules now make flexibility an obligation for new large loads: Texas PUCT 59220 (full curtailment on ERCOT instruction, 30-minute capability), Texas SB6 (≥75 MW remotely disconnectable), PJM's Board (large loads curtailed before pre-emergency DR) (R "Why a utility can order this"; [compliance.md](compliance.md)).
- EPRI DCFlex reports 10 to 30 % peak-reduction potential (R).
- Prior art shows the physics works at scale: Emerald AI's 25 % reduction for 3 h with SRP; Google's demand-response agreements; OpenAI agreeing to shed up to 1 GW of a 3.2 GW site (R "Prior art").

Brownout's part is the operator-facing loop that decides *which* work moves, gets the right people's yes, and
proves it with a meter.

## Not yet done (honest)
- Revenue-grade meter integration, Teams adapter, Entra Agent ID, Foundry Hosted Agent deployment: to be built.
- Multi-site coordination: not built (PLAN.md M7).
- Site-scale calibration: to be measured (per-cluster watt deltas replace the laptop's per-job deltas).
