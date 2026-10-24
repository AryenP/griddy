# Brownout — handoff (Fri 23 Oct, 11:30 PM PT)

Two machines, one repo (`github.com/AryenP/abc`, private). Read `CLAUDE.md`, `PLAN.md`, `SPEC.md`,
`DECISIONS.md` first; this file says where things stand and who owns what.

## Where it stands
M0–M3 are done, verified on the demo Mac, committed on `main`. Aryen decided at 11:30 PM to keep
going into M4 tonight (overrides KICKOFF.md's "do not start M4 tonight").

| Milestone | Evidence (all on the demo Mac) |
|---|---|
| M0 probe | powermetrics fields CPU/GPU/ANE/Combined, MPS ok, CAISO SP15 RT5 $50.33 @ 22:50 (DECISIONS.md) |
| M1 grid + meter | `runs/<id>/timeline.jsonl` with `grid` + `power` (1 Hz); `scripts/verify_feed.py` re-pulls OASIS raw: $48.67721 = $48.67721 MATCH |
| M2 workloads + calibrate | idle 1.35 W; chat +24.8 W (conc 4); train GPU +19.5 W / CPU +13.0 W; batch GPU +22.8 W / CPU +18.7 W |
| M3 dispatcher | `make solve`: OPTIMAL 0.06 s; train in Sat 14:00–16:00 at ~$5/MWh vs ~$36 skipped; chat conc 4 in all 96 slots |

Open problems (owner's call, not silently fixed): chat p95 is **9.7 s** at concurrency 4 / 256 tokens vs the
2 s SLA; emission factors in `config/isos.yaml` are uncited; batch is minutes of real work (18,794 man-page
passages), not 45 min; no operator/FDE quote yet (Sat 10 AM workshop).

## The split
**Rule: never edit the same file on both machines.** Anurag works on branches `anurag/<task>` and opens
PRs into `main`; the demo Mac reviews and merges. Plain commit messages, no co-author lines.

| Owner | Files | Why there |
|---|---|---|
| **Demo Mac (Aryen)** | `api/*`, `controller/*`, `workloads/*`, `dispatcher/*`, `grid/*`, `meter/*`, `core/*`, `Makefile`, `pyproject.toml`, `config/jobs.yaml`, `config/policy.yaml` | M4 execution loop, anything that needs this Mac's meter, calibration or evidence |
| **Anurag** | `web/*`, `scripts/qr.py`, `agent/*`, `tests/test_agent*.py`, `tests/test_web*.py`, emission-factor block of `config/isos.yaml` | Pure frontend, agent layer and research; big downloads (Agent Framework/Azure SDKs) on fast internet |
| Shared, append-only | `DECISIONS.md` | Append your own lines in your PR; merges are trivial |

Need a dependency, a new type, or a config field from the demo Mac's files? Say so in the PR description;
don't edit those files.

### Anurag's tasks, in order
1. **Dashboard** `web/index.html` (+ `web/app.js`, `web/style.css`), SPEC §10, vanilla JS + Chart.js (pin an
   exact CDN version). Header claim + quote slot; row 1: measured watts (big), $/h at live price, gCO2/h at live
   mix, chat p95; row 2: 24-h price + carbon curves with the schedule painted on, current slot highlighted, feed
   age + "stale" badge; row 3: job cards; row 4: event log + solver explanations. "DISPATCHER OFF" toggle wired
   to `POST /api/dispatcher`. Every number shows its source and age. Phone-width safe.
2. **Phone pages** `web/chat.html` (talks to `POST /api/chat`) and `scripts/qr.py` (`make qr`: QR codes for
   `PUBLIC_URL/chat` and `PUBLIC_URL/owner`).
3. **Emission factors**: replace the numbers in `config/isos.yaml` `emission_factors_gco2_per_kwh` with a
   citable table (e.g. IPCC AR5 lifecycle medians or EPA eGRID), source in a comment, one DECISIONS line.
4. **Agent layer start (M5)** `agent/llm.py`: one interface; Claude via the `anthropic` SDK
   (`ANTHROPIC_MODEL` in `.env`), Microsoft Agent Framework + Foundry when `AZURE_AI_PROJECT_ENDPOINT` is set
   (`uv pip install -e ".[azure]"`); OpenTelemetry span per call; returns a clear "agent offline" result when
   no key/endpoint. Then `agent/explainer.py`: rewords `Schedule.explanations` + `GridSignal` into two
   sentences; it may not add facts (test that every number in the output appears in the input).
5. **OpenADR intake, deterministic path** `agent/intake.py`: parse an OpenADR 3.1 EVENT JSON
   (`IMPORT_CAPACITY_LIMIT`, `intervalPeriod`) into `core.types.CapEvent` with no LLM (a parser can do it).
   Free-text intake via the LLM comes after. Test against the example in RESEARCH.md.

### Demo Mac's tasks (tonight / Sat AM)
M4: `api/app.py` + `api/ws.py` + `api/routes.py` per the contract below; `controller/execute.py` (apply the
current slot via knobs, stop finished jobs, re-solve on new grid interval / policy change / CapEvent / job
finished / watts drift > 20%); verify watts follow the schedule across a slot boundary with no human input.
Then the chat SLA decision, `make baseline`, M6.

## API contract (built on the demo Mac; code the dashboard against this)
Server: `make demo` → `python -m api.app` on `HOST:PORT` from `.env` (default `0.0.0.0:8080`). Static
files served from `web/` at `/`, so `web/index.html` is `/` and `web/chat.html` is `/chat`.

**WebSocket `GET /ws`.** First message is a snapshot, then every timeline event as it is logged:
```json
{"kind": "snapshot", "data": {
  "grid": GridSignal | null, "schedule": Schedule | null, "plan": Plan-for-current-slot | null,
  "power": PowerReading | null, "jobs": {"chat": status, "train": status, "batch": status},
  "calibration": Calibration | null, "policy": Policy, "iso_options": ["CAISO", "ERCOT"],
  "dispatcher_enabled": true, "agent": "online" | "offline"}}
{"t": 1792822585.31, "kind": "power",    "data": PowerReading}
{"t": ...,           "kind": "grid",     "data": {"feed": "signal", ...GridSignal}}
{"t": ...,           "kind": "schedule", "data": Schedule}
{"t": ...,           "kind": "plan",     "data": {"slot_start": iso8601, "actions": [...], "on_last_known_data": bool}}
{"t": ...,           "kind": "state",    "data": {"job": "train", ...status}}      // ~1 Hz per job
{"t": ...,           "kind": "action",   "data": {"job": "train", "state": "run", "previous": {...}}}
{"t": ...,           "kind": "latency",  "data": {"p95_60s": 1.8, "n_60s": 12}}
{"t": ...,           "kind": "note" | "shortfall" | "policy" | "event", "data": {...}}
```
Field names are exactly the pydantic models in `core/types.py` (`model_dump(mode="json")`). Job status
objects are what the workloads write to `runs/control/<job>.status.json` (see `workloads/*.py`):
train has `step`, `loss`, `rate` (steps/s); batch has `items_done`, `total`, `fraction`, `rate` (items/s);
chat has `concurrency`, `inflight`, `p95_60s`, `n_60s`, `max_tokens`, `model`. All have `state`, `device`, `t`.

**HTTP**
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/state` | | the snapshot `data` above |
| POST | `/api/policy` | `{"objective"?: "cost"\|"carbon"\|"balanced", "power_cap_w"?: number\|null}` | new Schedule (re-solved) |
| POST | `/api/iso` | `{"iso": "CAISO"\|"ERCOT"}` | new GridSignal + Schedule |
| POST | `/api/dispatcher` | `{"enabled": bool}` | `{"enabled": bool}`; off = baseline (run everything) |
| POST | `/api/chat` | `{"messages": [{"role","content"}], "max_tokens"?: int}` | `{"reply", "latency_s", "tokens", "max_tokens"}` |

Real captured timelines for building against before the API is up: `tests/fixtures/real_timeline_*.jsonl`
(see `tests/fixtures/README.md`). Feed them in from the browser console; no replay mode in the code.

Units: watts W, prices $/MWh, carbon gCO2/kWh; $/h = W/1e6 × $/MWh; gCO2/h = W/1000 × gCO2/kWh.

## Setting up Anurag's machine
```bash
git clone https://github.com/AryenP/abc.git brownout && cd brownout
cp .env.example .env            # add ANTHROPIC_API_KEY yourself; never commit .env
make setup                      # uv + Python 3.11 + deps (torch is large: fast internet helps)
make test
```
If it is an Apple-silicon Mac you can run the full stack for development: `brew install ollama`,
`OLLAMA_NUM_PARALLEL=4 ollama serve`, `ollama pull qwen3:4b`, then `sudo -v && make probe && make calibrate`.
That calibration describes YOUR Mac: it lives in `runs/` (gitignored) and is never used for demo numbers.
Not a Mac: skip the meter; work on `web/` against the contract and `agent/` with unit tests.

## Traps found tonight
- sudo's cache is per terminal: run `sudo -v` in the same terminal that starts anything with the meter.
- macOS 15 powermetrics repeats `GPU Power` after `Combined Power`; the meter splits on sample headers.
- Python output piped through `grep` is block-buffered; read `runs/<id>/timeline.jsonl` for live progress.
- Never run two `ollama pull`s at once; it corrupts the partial download.
- PJM needs `PJM_API_KEY`; without it PJM is hidden. CAISO and ERCOT are keyless.
- Slots are in the ISO's local time; CAISO day-ahead covers the whole horizon at night.

## Prompt for Anurag's Claude Code (paste as-is)
```
Read CLAUDE.md, PLAN.md, SPEC.md, DECISIONS.md and HANDOFF.md fully before writing code. You are the
second machine on Brownout. The judge demo runs on Aryen's Mac, not this one; nothing measured here is
ever a demo number.

1. Setup per HANDOFF.md "Setting up Anurag's machine": make setup, make test (must be green). Report
   whether this machine is Apple silicon; if it is, also bring up Ollama + qwen3:4b and run
   `sudo -v && make probe` (ask me to type the sudo password in the terminal).
2. Work only on the files HANDOFF.md assigns to Anurag, in the order listed (dashboard, phone pages +
   qr, emission factors, agent/llm.py + explainer, OpenADR intake). Never edit a file owned by the demo
   Mac; if you need a change there, write it in the PR description.
3. One branch per task: anurag/<task>. Commit small, plain messages, no co-author lines. Push the
   branch and open a PR into main with: what it does, how you tested it, what you need from the demo Mac.
4. Code the dashboard against the API contract in HANDOFF.md exactly (field names from core/types.py).
   Before the demo Mac's API exists, test the dashboard with the REAL captured timelines in
   tests/fixtures/real_timeline_*.jsonl, fed in from the browser console only; do not add a replay or
   mock mode to the code.

Rules you must not break: nothing simulated or hardcoded reaches the judge; the solver decides, the LLM
explains/negotiates, the controller executes (the agent gets no code path to any knob); every claim shows
its source and age; no dead code or stubs; no secrets in the repo. For any LLM call ask "could the solver
or a regex do this?" and if yes, move it. Stop after each task's PR and show me the evidence.
```
