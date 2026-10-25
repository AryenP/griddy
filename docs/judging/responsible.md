# Responsible design

The rule from day one (CLAUDE.md): **the solver decides, the LLM explains and negotiates, the controller
executes**. Numbers below cite `DECISIONS.md` (**D hh:mm**) or the eval reports.

## 1. The LLM has no path to a knob
- Knobs (run/pause, concurrency, threads, GPU/CPU) live in `controller/knobs.py` and are called only by the executor, which applies the CP-SAT schedule's current slot (`controller/execute.py`).
- The agent layer (`agent/`) returns data only: an `IntakeResult` (a cap or policy change for the solver to plan with), an `OwnerDecision`, an `Explanation`. The runtime decides what to do with it (team/README.md rule 5).
- The schedule is deterministic and reproducible from its inputs (D 23:50).

## 2. People approve the risky actions
- If a cap can only be met by breaking a job's deadline, the job's **owner** is asked first, in free text: "approve", "no, <reason>", or a new time.
- If the owner refuses, the solver can only go over the cap, and the **operator** is asked. Until the operator says yes, the plan that actually runs **holds the utility's cap** and lets deadlines slip (D 02:55). A "no" is not asked again for the same caps.
- The only exception is when nothing fits under the cap at all, i.e. the minimum load is above it. The plan says so in its own words ("over the cap without approval: nothing fits under it").
- Every request, reply, decision and who made it lands in the timeline and in the run report's approvals table.

## 3. No invented numbers
- The explainer and the negotiator accept LLM wording only if **every number in it already appears in the solver's facts** (rounding allowed). Otherwise they show the facts verbatim (D 15:00 agent-layer entry; `agent/explainer.py` `ungrounded`).
- The dashboard labels every number by kind: *measured* (powermetrics), *planned (calibrated)*, or the grid feed with its age. It says STALE when a feed is old, and "not priced" instead of a fake zero.

## 4. Requests are data, not instructions
- Plain forms ("30% for 20 minutes", "cap at 15 W until 1 AM", "yes", "no, …", "ok if done by Tuesday noon") are parsed by rules and never reach a model (D 15:00).
- Free text that tries to operate a knob, forge an approval, lift the utility's cap, change another owner's deadline or extract secrets is **rejected**, deterministically where possible. Azure AI Content Safety Prompt Shields runs first when configured.
- Owner replies with a bare hour ("Tuesday 9") ask "AM or PM?" instead of guessing (D 03:00).

### Eval results (`evals/cases.yaml`, 90 cases)
| run | mode | pass | fail | needs a model | injections |
|---|---|---|---|---|---|
| [docs/judging/evals.md](evals.md) (current main, offline) | rules only, no model | 74 | 0 | 16 | **12/12 rejected** |
| `docs/evidence/evals-live-20261024-2033.md` (Sat 20:33, 138 cases with the fault reader) | claude-sonnet-5-5 | 135 | 3 | 0 | **19/19 rejected** |
| `docs/evidence/evals-live-20261024.md` (D 02:45) | claude-sonnet-5-5 | 86 | 4 | 0 | **12/12 rejected** |

The four live misses are judgment calls, and none is unsafe:
- "halve it for 45" was read as a 50 % cap for 45 min.
- Two out-of-scope requests were rejected instead of answered with a question.
- "Tuesday 9" was read as 9 AM. This is now fixed by a rule.

## 5. Offline is a mode, not a failure
With no model key or endpoint the dashboard shows **"agent offline"**. The plain forms keep working, explanations
show the solver's facts, and the solver and controller never stop (CLAUDE.md non-negotiable 5; DEMO.md failure drills).

## 6. Everything is on the record
- **Timeline:** every run writes `runs/<id>/timeline.jsonl`: grid signals, schedules, plans, knob actions, power at 1 Hz, approvals, shortfalls. Reports and comparisons are computed from it only.
- **Traces:** one OpenTelemetry span per agent decision (model, latency, tokens, whether the LLM was used, rejected numbers), shown on the dashboard's audit trail and exported to Application Insights when configured.
- **Evidence hygiene:** power evidence is only valid with the Mac otherwise idle, because powermetrics measures the whole chip (D 01:50). Overlapping calibrations were thrown out and re-run (D 02:09).

## Open items
- Content Safety and Foundry are not provisioned yet (team/2-anuraag.md task 9). Until then Prompt Shields does not run, and injection rejection relies on the rules above, shown in the table.
- The three-policy run showed load Brownout did not start pushing the machine over the cap. That load is now measured and counted (D 03:55); the re-run is **to be measured**.
