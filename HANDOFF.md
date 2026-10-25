# Brownout — handoff (updated Sat 24 Oct, 1:00 AM PT)

Two machines, one repo (`github.com/AryenP/abc`, private). Read `CLAUDE.md`, `PLAN.md`, `SPEC.md`,
`DECISIONS.md` first; this file says where things stand and who owns what.

## Where it stands
M0–M4 are done and verified on the demo Mac (`demo-stable-1`). Every machine starts from KICKOFF.md,
then the "Start now" block in its `team/<n>-<name>.md`. Machines 3 and 4 have finished phase 1 on
branches; their first job is a rebased PR each.

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
chat has `concurrency`, `inflight`, `p95_60s` (total latency), `ttft_p95_60s` (time to first token), `n_60s`, `busy_60s` (avg requests in service, the traffic the plan uses), `max_tokens`, `model`. All have `state`, `device`, `t`.

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
| POST | `/api/approvals/{id}/reply` | `{"text": str, "who": str, "owner"?: str}` (`owner`: the owner this console acts as, else `who`; any other owner gets 403) | `{"decision": OwnerDecision, "schedule": Schedule \| null}` |
| GET | `/api/explain` | | `Explanation` for the current schedule |
| POST | `/api/ask` | `{"question": str}` operator asks "why is training paused?" | `Explanation` answered from live state only |
| GET | `/api/report?run=<id>\|latest` | | `Report` |
| GET | `/api/compare?dispatched=<id>&baseline=<id>` (or `baseline_policy=baseline\|pause_all` for the newest of that policy) | | `Comparison` |
| GET | `/api/runs` | | `[{"run_id", "started", "dispatcher_enabled", "policy", "machine", "of_record"}]`, oldest first; `of_record` (since Sat 17:38) marks the evidence comparisons of record in docs/evidence/claims.yaml; `policy` is `dispatcher` \| `baseline` (ignore the call) \| `pause_all` |
| GET | `/api/cities` | | since Sat 18:06: `[{"id", "name", "iso", "viewbox": [west, north, east, south], "hospitals": [{"name", "lat", "lon", "osm"}], "source", "license", "fetched_at"}]`: the city a judge opens from the 3D world, its hospitals REAL (OpenStreetMap, ODbL; credit it on the page). Feeders and blocks drawn around them are illustrative: say so |
| GET | `/api/cities/{id}/map` | | since Sat 19:59: one real square of the city drawn 1:1, `{"city", "area", "center": [lat, lon], "half_m", "fetched_at", "source", "license", "heights": {"tagged", "levels", "estimated"}, "buildings": [{"p": [[x, z]] (metres from the centre, x east, z south), "h", "h0", "hospital"?, "name"?}], "roads": [{"w" (1-5, by class), "p", "name"?}], "parks": [[[x, z]]], "water": [...], "power_lines": [{"kind", "p", "voltage"?}], "power_sites": [{"kind", "x", "z", "name"?}], "hospitals": [{"name", "x", "z", "outline"}]}`; OpenStreetMap (ODbL): credit it, and say which heights are estimated |
| GET | `/api/replay/events` | | `[{"id", "title", "when", "iso", "ba", "timezone", "window": [start, end] (local ISO), "series": [[hour-ending ISO, demand_mw, demand_forecast_mw]], "alerts": [{"kind": warning\|emergency\|outage\|end\|brownout, "label", "source", "at" (local ISO) or "day", "before_window", "replay_s", "cut_pct"?}], "impact": [{"text", "source"}], "shed_mw", "people_out", "people_unit", "flexible_mw", "flexible_source", "record_mw", "record_source", "report_url", "data_source"}]`: REAL grid emergencies (EIA-930 data, cited alerts; since Sat 16:30) |
| POST | `/api/replay` | `{"action": "start", "event": id}` or `{"action": "stop"}` (+ optional `"who"`) | start or stop a replay through the live software; each alert reaches the real dispatcher at its real time. Since Sat 17:19 a start first fetches the event's hours live from api.eia.gov (a few seconds; the evidence copy if unreachable) and returns `"data": {"source": "live" \| "evidence copy", "fetched_at", "rows", "url", "max_diff_mw" (live vs evidence copy), "why" (if not live)}` |
| POST | `/api/whatif/read` | `{"text": the judge's words (3-500 chars), "target": the clicked part or null}` (+ optional `"who"`) | since Sat 17:27: reads the words into `{"target", "share_pct", "cause", "how" ("read by pattern" or "read by <model>"), "size_mw", "part_mw"}`; breaks nothing. 422 with a reason the page can show (words screened as instructions, not a grid failure, agent offline, a part producing nothing); rate-limited like /api/ask |
| POST | `/api/whatif` | `{"target": "plant:<Gas\|Coal\|Nuclear\|Wind\|Solar\|Hydro\|Imports>" \| "hub" \| "city" \| "clear", "share_pct": 1-100 (default 100), "cause": the judge's words (optional)}` (+ optional `"who"`) | a judge breaks a part (since Sat 17:19): the fault is invented, its size is real (that fleet's output at this moment; the hub: the largest fleet; the city: demand to the rest of the day's published forecast peak). Returns the first `whatif` state; 404 for an unknown part, 409 when there is nothing to break |
| POST | `/api/sites/{site_id}/beat` | a laptop's heartbeat (fleet/agent.py): `{"t", "watts" (its battery's reading, null when plugged in), "meter_t", "meter_note", "plugged", "running", "done_mb", "rate_mb_s", "machine"}` | `{"site", "run": bool}`, its plan; 404 for a site not in config/fleet.yaml (since Sat 05:10); when `.env` sets FLEET_TOKEN, both laptop routes need header `X-Brownout-Fleet-Token` or answer 401 (since Sat 08:40) |
| POST | `/api/sites/{site_id}/calibration` | the laptop's own calibration `{"idle_w", "delta_w", "rate_mb_s", "samples", "window_s", "threads", "measured_at", "machine", "meter"}` | `{"site", "status": "stored"}` |
| GET | `/api/runs/{run_id}/series` | | `{"run_id", "policy", "dispatcher_enabled", "machine", "started", "ended", "power": [[t, W]], "caps": [{"id", "start", "end", "target_w", "target_pct", "source", "reason"}], "actions": [{"t", "job", ...}], "shortfalls": [{"t", "shortfall_kind", "job_id", "message"}]}`: the measured record for drawing (since Sat 03:40). Run ids only: a path is a 404 on every run route |
| GET | `/api/trace?n=50` | | recent OpenTelemetry spans `[{"name","start","end","attributes",...}]` |
| GET | `/join?t=<token>&next=/operator.html` | | 303 to `next` (same-site paths only) with the HttpOnly `brownout_op` cookie; wrong token 401 (since Sat 14:45) |

**At grid scale (since Sat 14:53, grid/scale.py).** The snapshot carries `"scale"` (null until the first fetch) and every
`poll_s` (300 s) the WebSocket sends `{"kind": "scale", "data": {"estimate": true, "iso": "ERCOT", "demand_mw" (ERCOT's live
actual system demand), "demand_t", "large_loads_running_mw", "large_loads_approved_mw", "large_loads_source", "large_loads_url",
"queue_gw", "queue_source", "queue_url", "our_cut_pct", "our_cut_source", "freed_mw", "share_of_demand_pct"}}`. It is an
ESTIMATE (arithmetic on cited public numbers and this Mac's measured cut): label it so on every page; only `demand_mw` is live.

**Who may act (since Sat 14:45, Microsoft HVE Core review; api/access.py).** Every POST that moves a knob, a cap or an
approval (`/api/policy`, `/api/iso`, `/api/dispatcher`, `/api/jobs/{id}`, `/api/event`, `/api/replay`, `/request`,
`/openadr/event`, `/api/approvals/{id}/reply`, `/api/ask`) answers **401** unless the caller is this Mac (loopback or its own
LAN address) or a device that joined: the `brownout_op` cookie from `/join`, or the token in `X-Brownout-Token`. The token
is `OPERATOR_TOKEN` (.env), else `api.access.operator_token()` (runs/.operator_token). Reads (`/api/state`, approvals,
runs, reports, `/ws`) and chat stay open. `/request` and `/api/ask` also answer **429** past 10 calls a minute from one
device. Every switch body takes an optional `"who"` (default "operator"); the timeline records it as
`"<who> (this Mac | joined operator device <ip> | joined owner device <ip>)"`. The `power_cap` approval is decided by
rules only: a plain yes approves, a no holds the cap, anything else comes back `unclear` and stays pending.
**Roles (since Sat 20:28, HVE Core re-check 20:16).** Two join tokens: `OPERATOR_TOKEN` (runs/.operator_token) joins a phone
as the utility, `OWNER_TOKEN` (runs/.owner_token) as a job owner; `make qr` puts each in its page's QR code. An
operator device may use every route above except a job owner's approval; an owner device may answer its own job's
approvals (`/api/approvals/{id}/reply` for a request whose `job_id` is not `power_cap`), set a job's deadline
(`/api/jobs/{id}`) and `/api/ask`, and gets **403** elsewhere (the dispatcher, policy, caps, requests, replays, what-ifs,
the `power_cap` approval). This Mac may do everything.

WebSocket adds `{"kind": "approval", "data": ApprovalRequest}` whenever a request is created or changes
status (and `{"kind": "approval", "data": {"request_id", "who", "decision": OwnerDecision}}` for each reply),
and the snapshot gains `"approvals": [ApprovalRequest]` (all statuses), `"explanation": Explanation | null`
`"agent_model"`, and `"cap_events": [CapEvent]` (the caps in force or upcoming, `target_w` resolved). Since Sat 16:30 (replacing the simulated neighbourhood, removed) the snapshot carries `"replay": {"enabled", "seconds", "active" (event id or null), "events": [{"id", "title", "when", "iso"}], "last"}` and, once a second while a replay runs, the WebSocket sends `{"kind": "replay", "data": {"t", "event", "title", "sim_time" (the event's local time being replayed), "progress", "demand_mw", "forecast_mw", "gap_mw" (forecast minus served: load that went unserved), "carbon_g_kwh", "mix_mw" ({EIA-930 fuel: MW} at that hour), "fired" (alert labels so far), "cut_kinds", "baseline_w", "ours_w" (measured), "measured_cut_pct", "nothing_to_shed", "scale": {"freed_mw", "flexible_mw", "flexible_source", "share_of_shed_pct", "people", "people_unit"} or null, "hour_ending" (since Sat 17:19: the last hour that has ENDED at sim_time; every grid number is that hour's, never a later one), "data" (where the hours came from, as in POST /api/replay)}}`. While a what-if runs the WebSocket sends `{"kind": "whatif", "data": {"t", "target", "fuel", "label", "source", "event", "mix_mw", "lost_mw", "surge_mw", "served_before", "needed_before", "served_after", "needed_after", "shortfall_mw", "asked_cut_pct", "baseline_w", "ours_w", "measured_cut_pct", "nothing_to_shed", "remaining_s", "scale": {"freed_mw", "share_pct", "flexible_mw", "flexible_source", "share_of_shortfall_pct", "people", "people_unit"} or null}}` once a second (the snapshot's `"whatif"` is the last one or null); its CapEvents have `source: "whatif"`. Label the fault "what-if". The grid's numbers are REAL (EIA-930) and the alerts cited; `scale` is an ESTIMATE: label it so. CapEvents from a replay have `source: "replay"`. Since Sat 05:10 the snapshot carries `"fleet": [{"id", "name", "owner", "status" ("online" or why not), "watts", "run", "running", "done_mb", "rate_mb_s", "machine", "calibration", "last_beat"}]` (empty without laptops), and while any laptop is online every Mac power sample is followed by `{"kind": "fleet_power", "data": {"t" (the Mac sample's t), "mac_w", "sites": {id: W}, "combined_w"}}`, the total the cap is judged on. Since Sat 04:10 the snapshot also carries `"power_history": [[t, W]]`, the executor's measured combined watts for the last hour (1 Hz), so a page drawing a live trace starts full. Parsed
requests are logged as `{"kind": "intake", "data": {"intake": IntakeResult, "who"}}` (since Sat 03:15; before
that they shared the `event` kind); `event` now only ever carries a CapEvent. Each new schedule's explanation arrives as `{"kind": "note", "data": {"schedule_id",
"explanation": Explanation}}`. Shortfall events carry `shortfall_kind` (`deadline` | `cap` | `sla`), not `kind`. Since Sat 10:08 (b06cd51) an `sla` shortfall with `job_id: "chat"` comes with a cap shortfall when slowing chat would help: `amount` is the WATTS slowing it would save (not seconds), `message` says how far and that requests would queue. Chat keeps full concurrency until the operator answers no to going over the cap. `Calibration.jobs.chat.gpu.streams_w` (`{busy streams: delta W}`) is chat's measured curve. `Schedule.background_w` (since Sat 03:55) is measured load outside the plan that the solver counted against the cap, and `planned_w` includes it; a re-solve for it logs `{"kind": "note", "data": {"msg": "re-solve: load outside the plan ...", "trigger": "background", "background_w"}}`.
Approval flow (live on main since Sat 01:45): the owner of a job is asked first whenever a deadline could
slip; `approve` -> the slipped finish becomes the deadline, a new time -> that deadline, `no ...` -> the
deadline turns hard and the solver goes over the cap instead, which creates an operator request with
`job_id: "power_cap"`, drafted by `negotiator.draft_operator_ask` (carries the owner's refusal reason). The
operator's `no` holds the cap and, since Sat 10:08, lets the plan slow chat for those caps only
(`Executor.hold_cap`, a `policy` event "operator refused going over the cap: chat may be degraded to hold it").
`POST /api/ask` is live: `{"question"}` -> `Explanation` from the live state; instructions in the question are
refused, never acted on. Intake now returns `kind: "rejected"` (with `reason`) for injection attempts.
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
`OLLAMA_NUM_PARALLEL=4 ollama serve`, `ollama pull qwen3:4b-instruct` (not plain `qwen3:4b`: that build always thinks), then `sudo -v && make probe && make calibrate`.
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
