# 1 Aryen: runtime and integration (the demo Mac)

**Mission:** everything that runs on the demo Mac works end to end, and every other machine's work
lands in it. You own the contract (HANDOFF.md API, `core/types.py`) and merge all PRs.

**Owns:** `api/`, `controller/`, `dispatcher/`, `grid/`, `meter/`, `workloads/`, `core/`, `config/jobs.yaml`,
`config/policy.yaml`, `Makefile`, `pyproject.toml`, `team/`, `HANDOFF.md`, tests for those, fixtures.

## Tasks, in order
1. **M4 execution loop** (in progress Fri 11:35 PM). `make demo` up; watts follow the schedule across a
   slot boundary with no human input. Done when: a timeline shows a `plan` change at a slot boundary and
   `power` dropping/rising within seconds of it.
2. **Chat SLA decision.** Measured p95 9.7 s at concurrency 4 / 256 tokens vs a 2 s SLA. Measure TTFT with
   streaming in `workloads/chat_proxy.py`, sweep max_tokens and concurrency, set the SLA from data, log it.
   Done when: policy SLA equals a measured number and chat meets it at the planned concurrency.
3. **Wire machine 4's agent** as their PRs land: `POST /request`, `POST /openadr/event`, approval flow
   (`GET /api/owner/{owner}/pending`, `POST /api/owner/{owner}/reply`), explainer text in `schedule` events,
   `agent` online/offline in the snapshot. Done when: DEMO.md 1:15–2:30 runs on the Mac.
4. **Wire machine 3's receipts**: `GET /api/report`, `GET /api/compare`, `GET /api/trace`, call
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
