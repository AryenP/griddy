# Brownout

When the grid runs short, the plan for AI data centers is diesel generators. This is the alternative.

Brownout is a grid-aware compute dispatcher. It watches the live grid (real ISO prices, day-ahead
curve, load forecast, fuel mix, alerts), schedules every AI job over the next 24 hours with a CP-SAT
solver, executes the current slot on real hardware, asks job owners before breaking their deadlines,
and proves the result with measured power. Built at Cal Hacks 13.0 for the Microsoft Challenge.

Nothing is simulated: every price, watt and dollar on screen is live or measured, with its source and age.

### Diesel and "pause everything" are the naive answers. Brownout is the intelligent one.

When a utility asks a data center to cut load, the options today are blunt: start backup generators,
ignore the request, or switch off everything that can be switched off. Brownout decides per job and per
15-minute slot instead, keeps the service people are using fast, asks before it breaks anyone's deadline,
and proves what it did with measured watts.

| | Backup diesel | Ignore the call | Pause everything | **Brownout** |
|---|:---:|:---:|:---:|:---:|
| Grid draw under the utility's cap | ✅ | ❌ | ✅ | ✅ in seconds |
| No on-site combustion | ❌ | ✅ | ✅ | ✅ |
| Interactive service stays up | ✅ | ✅ | ⚠️ only if spared by hand | ✅ never paused |
| Deferred work still meets its deadline | ✅ | ✅ | ⚠️ no rescheduling | ✅ re-planned around the cap |
| Flexible work moves to cheap, clean hours every day | ❌ | ❌ | ❌ | ✅ live prices + fuel mix |
| Owners asked before a deadline slips | n/a | n/a | ❌ | ✅ in plain words |
| Says honestly when the cap can't be met | n/a | n/a | ❌ | ✅ the solver's own shortfall |
| Compliance proven with measured power | n/a | ❌ | ❌ | ✅ every second, timestamped |

## The proof: early, but pointed
Same jobs, same live grid, same request (a cap 30 % below the measured baseline, starting 2 min in, for
5 min; training due 2 h out), once with the dispatcher off and once with it on. Measured by macOS
powermetrics on one M2 Pro; computed from the runs' timelines only.

| Run (code) | Mode | Mean power in the cap window | Seconds at or under the cap | Time to compliance | Deadline |
|---|---|:---:|:---:|:---:|:---:|
| [02:28](docs/evidence/compare-20261024-022026-vs-20261024-021247-baseline.md) (e90eef1) | dispatcher off | 18.32 W | 0 % | never | planned ✅ |
| | **dispatched** | **0.68 W** | **99 %** | **5 s** | planned ✅ |
| [03:10](docs/evidence/compare-20261024-025349-vs-20261024-024609-baseline.md) (13f6b3b) | dispatcher off | 21.18 W | 0 % | never | planned ✅ |
| | **dispatched** | **1.64 W** | **99 %** | **7 s** | planned ✅ |

> Read this as a signal, not a guarantee: two short runs on a laptop, not a fleet, and the comparison here is
> against ignoring the call. A run against "pause everything" is next. Laptop watts make the dollar figures
> fractions of a cent; the claim is compliance in seconds with the work still delivered. The live
> request → owner refusal → operator approval run is in
> [docs/evidence/demo-flow-live-20261024.md](docs/evidence/demo-flow-live-20261024.md), and the responsible-design
> evals (86/90 live, all 12 injection attempts rejected) in [docs/evidence/evals-live-20261024.md](docs/evidence/evals-live-20261024.md).

## Who controls what
- **The utility** asks, in plain words or as an OpenADR 3.1 event. The request is parsed, read back with real
  numbers, and becomes a cap. It never becomes an instruction to the system.
- **The solver** (CP-SAT) decides every job's slots, device and concurrency from live prices, fuel mix, caps,
  deadlines and measured watts. It is deterministic and reproducible from its inputs.
- **Job owners** approve or refuse a deadline slip in their own words; a refusal makes the deadline hard.
- **The operator** decides when the cap and a refused deadline conflict. Until they approve going over the
  cap, the running plan holds it.
- **The controller** is the only code path to a knob. The LLM explains and negotiates; it cannot touch one.
- **The kill switch** is DISPATCHER OFF on the dashboard: every job runs as if Brownout weren't there.

## Run it (Apple-silicon Mac)
```bash
make setup            # uv env + deps (add the Azure extra: uv pip install -e '.[azure]')
cp .env.example .env  # add your keys; never commit .env. PJM also needs PJM_API_KEY (CAISO, ERCOT are keyless)
ollama pull qwen3:4b-instruct   # the chat model (plain qwen3:4b always thinks and leaks its reasoning)
sudo -v               # powermetrics needs sudo (or install the pinned passwordless rule: team/README.md)
make probe            # what this Mac supports: powermetrics, MPS, Ollama, a live CAISO price
make calibrate        # measure idle and each job's watts with powermetrics
make demo             # grid feeds + meter + workloads + dispatcher + dashboard on :8080
make baseline         # same jobs, dispatcher off, headless for 10 minutes, for the comparison
make evidence         # unattended: calibrate, then dispatcher-off and dispatched runs with the same scripted cap, compare
make report RUN=<id>  # reports/<id>.md + power chart, from that run's timeline only (default: latest)
make compare          # newest dispatched run vs newest baseline run (or DISPATCHED=<id> BASELINE=<id>)
make test
```
Azure (Application Insights for the decision trace): `azd auth login`, `azd provision`, then copy
`APPLICATIONINSIGHTS_CONNECTION_STRING` from `azd env get-values` into `.env`. Without the `[azure]`
extra or the connection string, spans stay in the in-memory buffer behind `/api/trace`.

## How it fits together
Grid watcher → CP-SAT dispatcher → controller on the Mac → powermetrics → timeline → dashboard,
report and comparison. The LLM handles messy intake, owner negotiation and explanations; it never
touches a knob. Diagram: [docs/architecture.md](docs/architecture.md). Interfaces: [SPEC.md](SPEC.md).
API contract: [HANDOFF.md](HANDOFF.md). Every decision taken during the build: [DECISIONS.md](DECISIONS.md).

## Where each sponsor tool is load-bearing
| Tool | What breaks without it |
|---|---|
| Microsoft Agent Framework + Foundry (`agent/llm.py`; Claude behind the same interface otherwise) | Free-text requests and owner replies beyond the plain forms, and the explanation prose. Plain forms ("30% for 20 minutes", "yes", "no, <reason>") and OpenADR JSON are parsed without the LLM, and explanations fall back to the solver's facts verbatim, so the UI shows "agent offline" and the loop keeps running |
| OpenTelemetry → Azure Application Insights (`telemetry/`, `infra/`, `azure.yaml`) | The audit log: no trace of who decided what, when, and why |
| OR-Tools CP-SAT (`dispatcher/`) | The schedule and the "how much can I still deliver" answer after a refusal |
| gridstatus: CAISO, ERCOT; PJM with `PJM_API_KEY` (`grid/`) | Live prices, fuel mix and alerts; the schedule would have nothing to optimise against |
| macOS powermetrics (`meter/`) | The proof: every watt in the report and the comparison |

## Receipts
- `agent/reporter.py` (`make report`, `/api/report`): pre-cap baseline (mean measured W over the 60 s
  before the cap starts), cap-window mean, % reduction, time to compliance (first sample whose trailing
  10-s mean is at or under the cap), energy, cost at the live price in effect each second, gCO2 at the
  live fuel mix, deadlines, approvals (who was asked, who answered, what), chat time-to-first-token p95
  (the SLA metric, `policy.sla.chat_ttft_p95_s` = 1.0 s) before and during with total-latency p95 beside
  it, shortfalls.
- `scripts/compare.py` (`make compare`, `/api/compare`): dispatched vs dispatcher-off over the same
  window length; a run's mode is the `dispatcher_enabled` of its "runtime start" note.
- Emission factors: IPCC AR5 lifecycle medians (CARB default for imports), cited per fuel in `config/isos.yaml`.

## Honest scope
One MacBook (Apple M2 Pro), SoC power (CPU + GPU + ANE) of roughly 1–30 W as `powermetrics` reports
it, not a wall meter. The feeds, solver, approvals and audit trail are the same loop at 50 MW; the
knobs there are cluster schedulers and power caps.

## Team
Four machines, one repo: [team/README.md](team/README.md).
