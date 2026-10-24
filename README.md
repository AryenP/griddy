# Brownout

When the grid runs short, the plan for AI data centers is diesel generators. This is the alternative.

Brownout is a grid-aware compute dispatcher. It watches the live grid (real ISO prices, day-ahead
curve, load forecast, fuel mix, alerts), schedules every AI job over the next 24 hours with a CP-SAT
solver, executes the current slot on real hardware, asks job owners before breaking their deadlines,
and proves the result with measured power. Built at Cal Hacks 13.0 for the Microsoft Challenge.

Nothing is simulated: every price, watt and dollar on screen is live or measured, with its source and age.

## Run it (Apple-silicon Mac)
```bash
make setup            # uv env + deps (add the Azure extra: uv pip install -e '.[azure]')
cp .env.example .env  # add your keys; never commit .env. PJM also needs PJM_API_KEY (CAISO, ERCOT are keyless)
ollama pull qwen3:4b-instruct   # the chat model (plain qwen3:4b always thinks and leaks its reasoning)
sudo -v               # powermetrics needs sudo; the cache is per terminal, so run the targets below here
make probe            # what this Mac supports: powermetrics, MPS, Ollama, a live CAISO price
make calibrate        # measure idle and each job's watts with powermetrics
make demo             # grid feeds + meter + workloads + dispatcher + dashboard on :8080
make baseline         # same jobs, dispatcher off, headless for 10 minutes, for the comparison
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
