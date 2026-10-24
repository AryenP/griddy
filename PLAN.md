# Brownout — build plan (dispatcher on one Mac; team of 2–3 + Claude Code)

Times Pacific. Each milestone has a "done when" that must be true on this Mac with live data. If a milestone runs 50% over, cut its stretch items. The non-negotiable trio by **Sat noon**: powermetrics on screen moving with the workloads, live prices from one ISO on the dashboard, the optimizer printing a readable schedule. Missing any of the three at noon → shrink to the facility-only version (cap events, no 24-h schedule) and still submit.

## Tonight (Fri 9 PM – 2 AM)
### M0 — Probe + skeleton (9:00–10:00)
- `scripts/probe_mac.sh`: `sudo powermetrics --samplers cpu_power,gpu_power -i 1000 -n 2`, Ollama present and a model pulled, `torch.backends.mps.is_available()`, `ortools` import, `gridstatus` pull of CAISO RT LMP.
- Repo layout per SPEC.md; `core/types.py` extended with GridSignal, Job, Policy, CapEvent, Schedule; `config/*.yaml` filled with real values.
- Done when: `make probe` prints watts, a CAISO price with its timestamp, and "MPS ok".

### M1 — Grid watcher + meter (10:00–11:30)
- `grid/watcher.py` polling CAISO (and ERCOT conditions) into `GridSignal` with feed age; `grid/carbon.py` from fuel mix with cited factors.
- `meter/powermetrics.py` streaming 1 Hz watts.
- Timeline logging of both.
- Done when: `runs/<id>/timeline.jsonl` fills with `grid` and `power` events and the price matches CAISO OASIS for the same interval.

### M2 — Workloads + knobs (11:30–1:00)
- `chat_proxy.py` over Ollama with semaphore; `train.py` on MPS with checkpoint/pause/resume; `batch.py` resumable.
- `controller/knobs.py` and `make calibrate` (per-job watt deltas and idle floor, measured).
- Done when: toggling each job visibly moves powermetrics and the calibration file holds measured deltas.

### M3 — Dispatcher v1 (1:00–2:00, finish Sat AM if needed)
- `dispatcher/model.py` CP-SAT with deadlines, cap, SLA, never_pause; `solve.py` with 2 s limit and minimal-relaxation on infeasibility; `schedule.py` explanations.
- Tests in SPEC §12 for the dispatcher.
- Done when: given the live price curve and `jobs.yaml`, `make solve` prints a 24-h schedule that puts the training job in the cheapest feasible slots before its deadline and keeps chat always on.

## Sleep 2–7 AM.

## Saturday
### M4 — Execution loop + dashboard (7:30–11:00; **10:00 Microsoft workshop, Theatre — one person goes, collects the quote, returns with it**)
- `controller/execute.py` applies the current slot; re-solve triggers wired; `api/app.py` + `ws.py`; `web/index.html` with the four live numbers, the price/carbon curves with the schedule painted on, job cards, event log, feed age.
- Done when: the Mac's watts follow the schedule across a slot boundary with no human input, and the dashboard shows it.

### M5 — Agent layer (11:00–2:30)
- `agent/llm.py` (Agent Framework/Foundry or Claude), `intake.py` (OpenADR + free text, Content Safety when configured), `negotiator.py` (free-text owner replies), `explainer.py`, `reporter.py`.
- `web/owner.html` on the judge's phone; `web/chat.html`.
- Done when: a typed emergency ("we need 30% off for 20 minutes, grid alert") re-solves, asks the training owner, a refusal in words changes the schedule, and the explanation on screen matches the solver's facts.

### M6 — Comparison + production hooks (2:30–5:30)
- `make baseline` (dispatcher off, same jobs, same window) and `scripts/compare.py`: cost $, gCO2, deadlines met, p95, watts under cap, time-to-compliance.
- OpenTelemetry → Application Insights (`azd provision`); trace shown on the dashboard as the audit log.
- Done when: the comparison renders from two logged runs and a trace of one decision is visible.

### Gate at 5:30 PM: is the core solid? If yes and time remains → M7. If not → M8 now.
### M7 — Optional, only if load-bearing (5:30–8:00)
- Fetch: grid-operator agent + dispatcher agent + site agent on Agentverse with ACP, ASI:One as the operator console (declare events, ask for the plan). Only if the three-agent split is real and the ASI:One flow completes the primary workflow. Otherwise skip.
- Foundry Hosted Agent deployment of the agent layer.
### M8 — Submission (8:00–11:00)
- Devpost draft by 10 PM: one-sentence problem, the diesel line, the four numbers, honest scope ("one Mac, 5–40 W; same loop at 50 MW"), opt-ins per TRACKS.md.
- Demo video (Hyphenate requires one): the refusal moment first, then the schedule moving with prices, then the numbers.
- README: architecture, run instructions, where each sponsor tool is load-bearing.
- Two full cold-start rehearsals with a teammate playing the judge.

## Sunday
- 7:00 freeze. 8:30 final Devpost edit. 8:50 deadline. 10:30 at the table: Mac, phone on owner page, QR cards, `DEMO.md`.
