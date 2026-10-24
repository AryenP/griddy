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

Chat SLA settled Sat 00:15: time to first token p95 <= 1.0 s (`policy.sla.chat_ttft_p95_s`), replies stream
(`/api/chat/stream`); measured worst 0.23 s. Open problems: emission factors in `config/isos.yaml` are uncited; batch is minutes of real work (18,794 man-page
passages), not 45 min; no operator/FDE quote yet (Sat 10 AM workshop).

## The split
Four machines. **`team/README.md` is the source of truth**: who is who (`team/roster.yaml`), each
machine's assignment (`team/<n>-<name>.md`), the rules, and the one prompt every machine pastes.
`uv run python scripts/team.py whoami` tells a machine who it is; `... check` refuses edits to files it
does not own. Machine 1 (this Mac, Aryen) is runtime and integration; 2 Anuraag frontend; 3 Krish
receipts, telemetry, Azure and submission; 4 Arumalla the agent layer.

## API contract (built on the demo Mac; code the dashboard against this)
Server: `make demo` → `python -m api.app` on `HOST:PORT` from `.env` (default `0.0.0.0:8080`). Static
files served from `web/` at `/`, so `web/index.html` is `/` and `web/chat.html` is `/chat`.

**WebSocket `GET /ws`.** First message is a snapshot, then every timeline event as it is logged:
```json
{"kind": "snapshot", "data": {
  "grid": GridSignal | null, "schedule": Schedule | null, "plan": Plan-for-current-slot | null,
  "power": PowerReading | null, "jobs": {"chat": status, "train": status, "batch": status},
  "calibration": Calibration | null, "policy": Policy, "iso_options": ["CAISO", "ERCOT"],
  "dispatcher_enabled": true, "agent": "online" | "offline", "run_id": str, "iso": str,
  "job_specs": {"train": Job, ...}, "quote": {"text", "who", "role"} | null}}
{"t": 1792822585.31, "kind": "power",    "data": PowerReading}
{"t": ...,           "kind": "grid",     "data": {"feed": "signal", ...GridSignal}}
{"t": ...,           "kind": "schedule", "data": Schedule}
{"t": ...,           "kind": "plan",     "data": {"slot_start": iso8601, "actions": [...], "on_last_known_data": bool}}
{"t": ...,           "kind": "state",    "data": {"job": "train", ...status}}      // ~1 Hz per job
{"t": ...,           "kind": "action",   "data": {"job": "train", "state": "run", "previous": {...}}}
{"t": ...,           "kind": "latency",  "data": {"p95_60s": 1.8, "n_60s": 12}}
{"t": ...,           "kind": "note" | "shortfall" | "policy" | "event", "data": {...}}
```
`job_specs` carries each job's owner, deadline (after any change), kind, priority, devices and derived
runtime (`Job` in core/types.py). `quote` comes from `config/site.yaml`. After `POST /api/iso` or
`/api/policy` the runtime logs `policy`, then `grid` (ISO switch) and `schedule` events on `/ws`.
Field names are exactly the pydantic models in `core/types.py` (`model_dump(mode="json")`). Job status
objects are what the workloads write to `runs/control/<job>.status.json` (see `workloads/*.py`):
train has `step`, `loss`, `rate` (steps/s); batch has `items_done`, `total`, `fraction`, `rate` (items/s);
chat has `concurrency`, `inflight`, `p95_60s` (total latency), `ttft_p95_60s` (time to first token), `n_60s`, `max_tokens`, `model`. All have `state`, `device`, `t`.

**HTTP**
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/state` | | the snapshot `data` above |
| POST | `/api/policy` | `{"objective"?: "cost"\|"carbon"\|"balanced", "power_cap_w"?: number\|null}` | new Schedule (re-solved) |
| POST | `/api/iso` | `{"iso": "CAISO"\|"ERCOT"}` | new GridSignal + Schedule |
| POST | `/api/dispatcher` | `{"enabled": bool}` | `{"enabled": bool}`; off = baseline (run everything) |
| POST | `/api/jobs/{id}` | `{"deadline": iso8601 \| null}` | new Schedule (owner/negotiator changed a deadline) |
| POST | `/api/event` | `{"start": iso8601, "duration_s": int, "target_w"?: W, "target_pct"?: % of measured baseline, "reason"}` | new Schedule with the cap |
| POST | `/api/chat` | `{"messages": [{"role","content"}], "max_tokens"?: int}` | `{"reply", "latency_s", "ttft_s", "tokens", "max_tokens"}` |
| POST | `/api/chat/stream` | same | NDJSON: `{"delta": str}` lines as tokens arrive, then `{"done": true, "latency_s", "ttft_s", "tokens", "max_tokens"}`; `{"error"}` on failure. **Use this for the phone chat page.** |

**Agent and receipts routes** (machine 1 wires them as machines 3 and 4 deliver; code against them now):
| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/request` | `{"text": str, "who"?: str}` free text or a voice transcript | `{"intake": IntakeResult, "schedule": Schedule \| null}` |
| POST | `/openadr/event` | an OpenADR 3.1 EVENT object | `{"intake": IntakeResult, "schedule": Schedule \| null}` |
| GET | `/api/approvals?owner=&status=pending` | | `[ApprovalRequest]` |
| POST | `/api/approvals/{id}/reply` | `{"text": str, "who": str}` | `{"decision": OwnerDecision, "schedule": Schedule \| null}` |
| GET | `/api/explain` | | `Explanation` for the current schedule |
| POST | `/api/ask` | `{"question": str}` operator asks "why is training paused?" | `Explanation` answered from live state only |
| GET | `/api/report?run=<id>\|latest` | | `Report` |
| GET | `/api/compare?dispatched=<id>&baseline=<id>` | | `Comparison` |
| GET | `/api/runs` | | `[{"run_id", "started", "dispatcher_enabled"}]` |
| GET | `/api/trace?n=50` | | recent OpenTelemetry spans `[{"name","start","end","attributes",...}]` |

WebSocket adds `{"kind": "approval", "data": ApprovalRequest}` whenever a request is created or changes
status, and the snapshot gains `"approvals": [ApprovalRequest]` and `"explanation": Explanation | null`.
Pages: `/` dashboard, `/chat` (or `/chat.html`), `/owner.html`, `/operator.html`.

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

## Prompt for each machine's Claude Code
Superseded: every machine pastes the single prompt in `team/README.md`; it identifies the machine and
opens the right assignment. (Anuraag: your earlier tasks moved; agent work is now machine 4's,
emission factors machine 3's. Your scope is `web/**` and `scripts/qr.py`.)
