# Brownout — architecture and interfaces (dispatcher, Mac edition)

## 1. One paragraph
A **grid watcher** pulls live ISO data (prices now and day-ahead, load forecast, fuel mix, system conditions, emergency events) and turns it into a per-interval cost and carbon signal plus a power budget. A **dispatcher** (CP-SAT) schedules every job over the next 24 hours against that signal and the jobs' deadlines, priorities and interruption rules, and re-solves whenever the signal, the policy or the job set changes. The **controller** executes the current interval on this Mac: which jobs run, at what concurrency, on GPU or CPU, paused or resumed. The **agent** (LLM) handles what the solver cannot: messy requests from a human operator or a utility, negotiating with job owners when a deadline must slip, writing the explanation and the compliance report. **powermetrics** measures what actually happened. Everything lands in the **timeline**; the **dashboard** shows it live.

```
 ISO feeds (gridstatus) ──▶ grid.watcher ──▶ GridSignal (price $/MWh, CO2 g/kWh, forecast, alerts, age)
 judge / utility ──OpenADR event · plain text · policy knobs──▶ agent.intake ──▶ Policy / CapEvent
                                                     │
                                            dispatcher.solve (CP-SAT) ──▶ Schedule (24 h, per 15-min slot, per job)
                                                     │                      + Plan for the current slot
 owner phone ◀── agent.negotiator ◀── deadline would break? ──┘
                                                     │
                                            controller.execute (this Mac) ── knobs: run/pause, concurrency, threads, GPU/CPU
                                                     │
                      workloads: chat (Ollama behind our proxy) · train (MPS, checkpointing) · batch (embeddings)
                                                     │                                   │
                                                     └──── timeline.jsonl ◀── meter.powermetrics (W, measured)
                                                                   │
                                   dashboard (WS) · reporter · compare (dispatched vs baseline)
```

## 2. Repo layout
```
brownout/
  CLAUDE.md PLAN.md SPEC.md DEMO.md RESEARCH.md TRACKS.md DECISIONS.md README.md KICKOFF.md
  pyproject.toml Makefile .env.example
  config/   policy.yaml jobs.yaml isos.yaml
  core/     types.py timeline.py config.py
  grid/     watcher.py isos.py carbon.py
  dispatcher/ model.py solve.py schedule.py
  controller/ execute.py knobs.py feasibility.py baseline.py
  agent/    llm.py intake.py negotiator.py explainer.py reporter.py channels/web.py
  meter/    powermetrics.py
  workloads/ base.py chat_proxy.py train.py batch.py
  api/      app.py ws.py routes.py
  web/      index.html owner.html chat.html
  scripts/  probe_mac.sh compare.py qr.py
  tests/
  runs/
```

## 3. Core types (pydantic; `core/types.py` is already written — extend, don't rewrite)
- `GridSignal`: iso, location, t, price_now ($/MWh), price_curve (list of (slot_start, $/MWh) for next 24 h: day-ahead hourly where available, else last RT), load_forecast (MW per hour), carbon_now (gCO2/kWh from fuel mix), carbon_curve, alerts (list[str]), feed_age_s, source_urls.
- `Job`: id, kind (`interactive|deferrable|droppable`), owner, priority, energy_kwh_est (from measured W × expected runtime), min_concurrency/max_concurrency, deadline (datetime|None), interruptible, checkpoint_interval_s, device (`gpu|cpu|either`), state, progress.
- `Policy`: objective (`cost|carbon|balanced`), weights, power_cap_w (optional), sla (chat p95 s), never_pause (list[job id]), approvals (who approves what).
- `CapEvent`: from OpenADR or text: start, duration_s, target (W or % of baseline), reason, raw.
- `Schedule`: solve_t, horizon slots (15 min × 96), per job per slot: run (0/1), concurrency, device; objective value; cost_$ and co2_g totals; deadline misses (list); explanations (solver-derived facts: which constraint bound what).
- `Plan` (current slot): actions for the controller + what needs approval.
- `TimelineEvent` kinds: `grid`, `policy`, `event`, `schedule`, `plan`, `approval`, `action`, `power`, `latency`, `state`, `shortfall`, `report`, `note`.

## 4. Grid watcher (`grid/`)
- Poll cadence: RT prices every 5 min (CAISO/PJM) or 15 (ERCOT), load forecast and day-ahead hourly every 30 min, fuel mix every 5 min, ERCOT real-time conditions every 1 min when ERCOT is selected.
- Calls (verified Fri 8:50 PM from the venue): `gridstatus.CAISO().get_lmp(date="today", market="REAL_TIME_5_MIN", locations=[...])` → columns incl. `LMP`, `Interval Start`; `get_load_forecast("today")` → 24 rows `Load Forecast`; `get_fuel_mix("today")` → MW by source; `gridstatus.Ercot().get_real_time_system_conditions()` → frequency, demand, capacity, wind, PV. PJM `get_lmp(date, market)` with `locations="hubs"`.
- Carbon: gCO2/kWh from the fuel mix using published emission factors in `config/isos.yaml` (cite the source in the file). Day-ahead carbon curve: use the day-ahead price curve shape as a proxy only if labelled "proxy"; otherwise show carbon for now only.
- Emergency inputs: ERCOT conditions (frequency < 59.9 Hz or reserves low → alert), plus explicit `CapEvent`s from the judge/utility.
- Every `GridSignal` carries `feed_age_s`; the dashboard shows it; > 2× cadence → "stale", plan marked "on last known data".

## 5. Dispatcher (`dispatcher/`)
CP-SAT model over 96 × 15-min slots:
- Variables: `run[j,s] ∈ {0,1}`, `conc[j,s] ∈ [min,max]`, `dev[j,s]` where allowed.
- Constraints: job energy must be delivered by its deadline (sum of slot energy ≥ required); interactive jobs always run with concurrency ≥ the SLA minimum; non-interruptible jobs run in contiguous blocks; power per slot ≤ cap (from policy or active CapEvent) using measured per-job watts; `never_pause` jobs never paused; approvals: a deadline may only be missed if an approval exists (else hard constraint).
- Objective: Σ slots (price × energy) weighted by policy.cost + Σ (carbon × energy) weighted by policy.carbon + penalty × lateness. Time limit 2 s; if infeasible, return the minimal relaxation (which deadline must slip, by how much, or how far over the cap) as a `Shortfall` for the agent to negotiate.
- Re-solve triggers: new grid interval, policy change, CapEvent, approval/refusal, job added/finished, measured watts drift > 20% from estimate.
- `explanations`: derived from the model (binding constraints, price deltas between chosen and rejected slots). The LLM may reword them; it may not invent them.

## 6. Controller (`controller/`)
- `execute(plan)` applies the current slot's decisions through `knobs.py`: `run/pause/resume(job)`, `set_concurrency(chat, n)` (proxy semaphore), `set_threads(job, n)` (`torch.set_num_threads` via a control socket / env on restart), `set_device(job, gpu|cpu)` (restart from checkpoint on the other device).
- `feasibility.py`: per-job measured watt deltas from `make calibrate` (toggle each job for 20 s, read powermetrics), idle floor; used by the solver's power constraint and by shortfall messages.
- `baseline.py`: no dispatcher: run every job as soon as submitted, full concurrency, ignore prices and caps. Same logging. This is the comparison.

## 7. Workloads (`workloads/`)
- `chat_proxy.py`: FastAPI in front of Ollama's OpenAI-compatible endpoint; `asyncio.Semaphore` is the concurrency knob; latency per request; p95 over 60 s; `max_tokens` clamp as degrade knob.
- `train.py`: small model on MPS, `torch.save` every N steps, cooperative pause via flag file at step boundaries, resume from checkpoint, reports step/s and energy used (W × time from the meter).
- `batch.py`: embeddings over a text list, resumable via `items_done`, runs on CPU or GPU as instructed.
- All implement `WorkloadControl`: `status()`, `start()`, `pause()`, `resume()`, `set_concurrency()`, `set_threads()`, `set_device()`.

## 8. Meter (`meter/powermetrics.py`)
`sudo powermetrics --samplers cpu_power,gpu_power -i 1000` streamed; parse `CPU Power`, `GPU Power`, `ANE Power`, `Combined Power` (mW). Expose watts at 1 Hz with timestamp. Attribution per job comes from calibration deltas, labelled "attributed", while the combined number is labelled "measured". `make probe` prints which fields exist on this Mac/OS.

## 9. Agent (`agent/`)
- `llm.py`: one interface; Agent Framework + Foundry when `AZURE_AI_PROJECT_ENDPOINT` is set, else Claude. OpenTelemetry span per call.
- `intake.py`: `POST /openadr/event` (OpenADR 3.1 event JSON) and `POST /request` (free text or voice transcript). Content Safety `shieldPrompt` on free text when configured. The LLM extracts a `CapEvent` or a `Policy` change, with ambiguity → one clarifying question to the operator.
- `negotiator.py`: when the solver's minimal relaxation needs a deadline to slip, message the owner (free text), parse the reply ("no, Monday 9 AM is a hard customer demo" → refusal with reason; "ok if it's done by Tuesday noon" → new deadline), feed the answer back as a constraint, re-solve.
- `explainer.py`: turns `Schedule.explanations` + the grid signal into two sentences an operator would read. It rewords solver facts; it does not decide.
- `reporter.py`: event-window report: baseline power vs event power, % reduction, time-to-compliance (s), cost and carbon vs baseline run, deadlines met, approvals with names and times, p95 before/during.

## 10. Dashboard (`web/index.html`)
Header: the customer quote and the claim ("When the grid runs short, the plan for AI data centers is diesel generators. This is the alternative."). Row 1: measured watts (big), $/h at the live price, gCO2/h at the live mix, chat p95. Row 2: the 24-hour price and carbon curves with the schedule painted on top (which job runs when), the current slot highlighted, feed age. Row 3: job cards (state, device, concurrency, progress, deadline, owner). Row 4: event log (grid alerts, events, plans, approvals, shortfalls) and the solver's explanation. A "DISPATCHER OFF" toggle runs the baseline policy live for the comparison.

## 11. Config (`config/`)
- `isos.yaml`: ISO → locations (e.g. CAISO TH_SP15_GEN-APND), markets, emission factors with source.
- `jobs.yaml`: the three jobs with owners, priorities, deadlines, interruption rules, device options.
- `policy.yaml`: objective weights, SLA, never_pause, approvals. **Replace owners/never_pause with what the FDEs say Saturday.**

## 12. Tests (`tests/`)
- dispatcher: deadline respected; cheap slots preferred when prices differ; cap respected; infeasible → minimal relaxation names the right job; never_pause honoured.
- grid: parsing of a saved gridstatus DataFrame fixture into `GridSignal` (fixture = a real pull saved to disk, labelled).
- controller: knob calls are idempotent; pause/resume round-trip on `train.py` with a tiny model.
- timeline: replay reproduces report numbers.
