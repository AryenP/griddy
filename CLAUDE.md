# Brownout — project rules for Claude Code

Brownout is a **grid-aware compute dispatcher**: it watches the electricity grid live (real ISO prices, load forecasts, fuel mix, emergency events), decides when and how each AI workload runs so power goes to what needs it, executes those decisions on real hardware, and proves the result with measured power. Built at Cal Hacks 13.0 (Fri Oct 23 – Sun Oct 25, 2026) for the **Microsoft Challenge Grand Prize** ("Built for the Real World": customer understanding, measurable usefulness, path to production, responsible design, end-to-end). Devpost due **Sun 8:50 AM PT**; live table demo Sun 10:30 AM.

Read `PLAN.md` (order), `SPEC.md` (architecture), `DEMO.md` (what the judge does), `RESEARCH.md` (verified facts), `TRACKS.md` (prizes). Unwritten decisions: pick the simplest option that keeps the demo real, log one line in `DECISIONS.md`.

## The machine
The demo runs on **this MacBook (Apple silicon)**. No external hardware. Power is measured with `sudo powermetrics` (CPU, GPU, ANE and combined watts), which is independent of our code. Knobs are concurrency, pause/resume, thread count and GPU-vs-CPU placement. There is no clock lock on a Mac; do not look for one.

## Non-negotiables
1. **Nothing simulated reaches a judge.** Every price, forecast, watt, latency and dollar on screen is live or measured. No synthetic grid data, no mocked meters, no canned plans. `make demo` never starts a simulator. The only fakes allowed are in `tests/` for unit-testing the solver and controller, labelled as test fixtures.
2. **The solver decides, the LLM explains and negotiates, the controller executes.** The LLM has no code path to any knob. The optimizer is deterministic and reproducible from its inputs.
3. **Two sources for every claim.** Grid data: the ISO feed with its timestamp and age shown. Power: `powermetrics` shown as measured, never estimated. If a feed is stale, the dashboard says so and the plan is marked "on last known data".
4. **Every run writes a timeline** (`runs/<id>/timeline.jsonl`). Reports, comparisons and the demo video come from timelines only.
5. **No hardcoding.** ISOs, locations, policies, SLAs, owners, models, endpoints come from `config/*.yaml` and `.env`. If the LLM is unavailable, the solver and controller keep running and the UI shows "agent offline".
6. **No dead code.** A feature is built and working or it is absent. Stretch items live in `PLAN.md`, not as stubs or TODOs.
7. **No secrets in the repo.** `.env` only; `.env.example` committed. Judges get source access. Plain commit messages, no AI co-author lines.

## Stack (fixed)
- Python 3.11, FastAPI + uvicorn, asyncio, pydantic v2, httpx, pandas. `uv`.
- Grid data: `gridstatus` (CAISO `REAL_TIME_5_MIN` LMP, `get_load_forecast`, `get_fuel_mix`; ERCOT `get_real_time_system_conditions`, `get_spp`; PJM `get_lmp`). Verified keyless from the venue network on Fri 8:50 PM.
- Optimizer: OR-Tools CP-SAT (`ortools`). Fallback to a greedy priority schedule only when CP-SAT exceeds its time limit, and say so in the plan.
- Power: `powermetrics --samplers cpu_power,gpu_power -i 1000` parsed by `meter/powermetrics.py` (requires sudo once; cache with `sudo -v`).
- Workloads on the Mac: chat via Ollama (`OLLAMA_NUM_PARALLEL` fixed; concurrency controlled by our proxy), a PyTorch MPS training loop with checkpointing, a batch embedding job. All three must visibly move `powermetrics`.
- Agent model: Microsoft Agent Framework (`agent-framework`) with `FoundryChatClient` when Azure is configured, otherwise `OpenAIChatClient` pointed at Claude via an OpenAI-compatible endpoint or the `anthropic` SDK behind the same `agent/llm.py` interface. Every call is an OpenTelemetry span; Application Insights when configured.
- Dashboard: `web/index.html`, vanilla JS + Chart.js, one WebSocket. The dashboard is the pitch; there are no slides.
- Owner/operator channel: `web/owner.html` on the judge's phone; Slack if time; Teams documented as the production adapter.
- Tests: pytest. `make test` green before every commit after M1.

## Working style
- Build in `PLAN.md` order; a milestone is done when its "done when" is true on this Mac.
- Small commits. `make demo` must come up from cold in under 2 minutes from M3 on.
- When the Mac behaves differently from `RESEARCH.md`, run `scripts/probe_mac.sh`, record it in `DECISIONS.md`, adapt.
- Delete scope before adding time. The judge sees four minutes.
- For every LLM call ask "could a regex or the solver do this?" If yes, move it out of the LLM.

## Commands
```
make setup      # uv env + deps
make demo       # live: grid feeds + powermetrics + workloads + dispatcher + dashboard
make baseline   # same jobs, no dispatcher (first-come, run-everything) for the comparison
make report RUN=<id>
make compare    # dispatched vs baseline numbers from logged runs
make test
make probe      # what this Mac supports (powermetrics fields, Ollama, MPS)
make qr         # QR codes for the judge's phone
```
