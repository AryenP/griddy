# 1 Aryen: runtime and integration (the demo Mac)

**Mission:** everything that runs on the demo Mac works end to end, and every other machine's work
lands in it. You own the contract (HANDOFF.md API, `core/types.py`) and merge all PRs.

**Owns:** `api/`, `controller/`, `dispatcher/`, `grid/`, `meter/`, `workloads/`, `core/`, `config/jobs.yaml`,
`config/policy.yaml`, `Makefile`, `pyproject.toml`, `team/`, `HANDOFF.md`, tests for those, fixtures.

## Fetch three-agent support (Sun 01:05, from Aryen; machine 2 builds the agents, see team/2-anuraag.md FA1-FA7)
Small and first, so machine 2 can test end to end:
1. **Roster.** Already done in this commit: member 2 owns `fetch_agents/**` (a new top-level folder, so it does not
   overlap your `agent/channels/**`) and `tests/test_fetch_three*.py`; the runbook goes in `docs/judging/` (already
   theirs). `tests/test_team.py` passes.
2. **`POST /request` with `"source": "fetch"`, loopback only.**
   - Intake parses the request as usual, but it is **not applied**. It becomes a pending operator approval
     (`job_id` "power_cap", owner `policy.operator`), with the readback and "asked by Grid Desk on ASI:One".
   - The response returns the approval id plus the readback and schedule preview.
   - The cap applies only on the operator's yes, from the operator phone page; a no is logged as a refusal.
   - Any other source keeps today's behaviour.
   - Tests cover all of this. Log one line in DECISIONS.
3. **`make fetch-three`** starts `fetch_agents/grid_desk.py`, `facility.py` and `verifier.py` in the same
   pinned uagents environment as `make fetch-agent`.
4. **.env.example:** add `FETCH_GRID_SEED`, `FETCH_FACILITY_SEED`, `FETCH_VERIFIER_SEED` and
   `FETCH_GRID_ADDRESS` (the address Facility and Verifier accept), with the same printf hint as
   `FETCH_AGENT_SEED`.
5. **When machine 2's PR lands:** merge it, run FA7 live with Aryen, and paste the README block and the Devpost
   Fetch line it sends. If FA7 doesn't pass, keep the single read-only agent and say so honestly in Devpost.

## Tasks, in order
1. **M4 execution loop** — DONE Fri 23:45 (DECISIONS.md). `make demo` up; watts follow the schedule across a
   slot boundary with no human input. Done when: a timeline shows a `plan` change at a slot boundary and
   `power` dropping/rising within seconds of it.
2. **Chat SLA decision.** Measured p95 9.7 s at concurrency 4 / 256 tokens vs a 2 s SLA. Measure TTFT with
   streaming in `workloads/chat_proxy.py`, sweep max_tokens and concurrency, set the SLA from data, log it.
   Done when: policy SLA equals a measured number and chat meets it at the planned concurrency.
3. **Wire machine 4's agent** as their PRs land: `POST /request`, `POST /openadr/event`, approval flow
   (`GET /api/approvals`, `POST /api/approvals/{id}/reply`, `approval` WS events), `/api/explain`, `/api/ask`,
   `agent` online/offline in the snapshot; shortfalls become ApprovalRequests via the negotiator. Done when: DEMO.md 1:15–2:30 runs on the Mac.
4. **Wire machine 3's receipts**: `GET /api/report`, `GET /api/compare`, `GET /api/runs`, `GET /api/trace`, call
   `telemetry.configure()` at startup. Run `make baseline` and a dispatched run over the same window.
   Done when: the comparison renders from two logged runs on this Mac.
5. **Merge machine 2's pages**; full DEMO.md rehearsal from cold (`make demo` < 2 min), failure drills.
6. Re-run `make calibrate` on the final setup Saturday evening; freeze Sunday 7:00.

## Contracts you provide
HANDOFF.md "API contract" plus the agent and receipts routes in task 3–4 (add them to HANDOFF.md
before wiring, so machines 2–4 can code against them). Types: bottom of `core/types.py`.

## Merging
Check out each PR, run `uv run python scripts/team.py check --member <their number>`, `make test`,
then merge. A PR that touches someone else's file goes back.

## Done Sat 03:35: the non-strawman comparison (`POLICY=pause_all`, `make evidence3`)
- **"Pause everything" baseline** (`POLICY=pause_all`): when a cap is active, pause every deferrable job and
  keep chat, no rescheduling; otherwise run everything. Add it to `controller/baseline.py` as a second
  dispatcher-off mode and to `make evidence` as a third run with the same scripted inputs, then show all three
  in the README proof table. Pick the scripted deadline so the difference is real (e.g. a cap long enough that
  pausing without rescheduling misses the deadline while Brownout's re-plan does not). Done when: the 3-way
  comparison renders from three logged runs and the README table shows it.

## Phase 2: when phase 1 is merged
7. **Second grid end to end.** ERCOT (`POST /api/iso`) live for a full slot: schedule repaints, watts follow;
   ERCOT frequency alert path exercised from real `system_conditions`. Done when: a timeline shows both ISOs.
8. **Traffic-aware chat watts** (unblocks the deferred drift re-solve trigger): plan chat power from measured
   per-request energy × observed request rate instead of full-traffic watts; then turn on the > 20% drift trigger.
9. **5:30 PM gate (PLAN.md):** core solid? Decide Fetch/Foundry Hosted Agent vs straight to submission; log it.
10. **Two cold-start rehearsals** with a teammate as the judge; fix whatever breaks; freeze Sunday 7:00.

## Overnight (Sat 04:05 to ~07:30, Aryen asleep), in order
Evidence is no longer re-run after every change: the only evidence run tonight is the scheduled final one at
06:40, on whatever main is then. From 06:30 until it finishes, light work only, and no runtime left running.
- **DONE 04:35: the interactive dashboard** (Aryen 04:05), live-checked with a real cap. **A. DONE 04:25: recorded the 03:47 evidence3 re-run** (evidence at aa8154e) in DECISIONS.md, the status file and vault 132.
  Done when: its two comparison tables and run ids are in DECISIONS.md.
- **B. Three-way proof table** in README.md and docs/devpost.md from the newest evidence3, with the 03:13 first
  pass and its fix told honestly in one line. Done when: both show ignore / pause everything / Brownout.
- **C. DONE 05:17 (DECISIONS 05:17): Second grid end to end** (task 7): `make demo`, switch to ERCOT with `POST /api/iso` for one full slot,
  schedule repaints, watts follow; back to CAISO. Done when: one timeline shows both ISOs; DECISIONS line.
- **D. DONE 04:50 (docs/rehearsal.md): Cold-start rehearsal by script**: from nothing running, time `make demo` to first schedule, curl every
  page and route in HANDOFF.md, run `make preflight`; fix what breaks. Done when: docs/rehearsal.md has a dated
  timing and every route answered.
- **E. Final evidence run** at 06:40 (scheduled), then record it like A and B, then `make tag-stable`.
- **F. Morning brief** at the top of team/status/1-aryen.md and in vault 132's summary: what changed overnight,
  the final numbers, what needs Aryen today. Done when: written after E.
- **DONE 06:08: simulated neighbourhood line** (Aryen 05:35, DECISIONS 05:45): model, real cap to the real
  dispatcher, dashboard panel with every simulated part labelled; live check 06:07 (diesel 0 vs 62.9 kWh simulated).

## Sat 10:20 to ~15:30 (Aryen away; sudo expired, so no power measurement until he is back), in order
- **DONE 10:08-10:30: chat under a cap.** Failed run recorded (789b777); fix b06cd51 (operator gate, measured
  chat curve); outside-load estimate prices chat from requests in service (abf8d53); dashboard says when chat is
  why power is over (03faf21); Devpost honest-scope lines (9569136); `make evidence-chat-judge` (7afdc13).
- **G (needs sudo).** `make evidence-chat && make evidence-chat-judge`, Mac idle ~20 min. Record both in
  DECISIONS, the brief, vault 132 and docs/devpost.md "Honest scope" (replace "not recorded yet" with the numbers,
  pass or fail). Done when: both reports are in docs/evidence/.
- **H (after G).** Live check with `make demo`: a cap, then one chat message during it; the dashboard says
  "chat is serving 1 request at full speed"; then `make tag-stable MSG=...` (demo-stable-4).
- **I (after H).** Real dashboard screenshots for the Devpost gallery (load trace with a cap, dispatch map, the
  operator ask on the phone page, the neighbourhood panel with its "simulated" tags).
- **Each tick meanwhile:** merge green teammate PRs, answer [supervisor] issues, keep queues at two or more.
