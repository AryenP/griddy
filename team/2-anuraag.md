# 2 Anuraag: frontend (everything the judge sees and touches)

**Mission:** the dashboard is the pitch; there are no slides. A judge must read the live grid, the
measured watts and the schedule at a glance, and act from their phone.

**Owns:** `web/**`, `scripts/qr.py`, `tests/test_web*.py`. Vanilla HTML/JS/CSS + Chart.js (pin an exact
CDN version). No build step. Must work at phone width.

**Talks to:** machine 1's API (HANDOFF.md contract; `/ws` + `/api/*`). Field names are the pydantic models
in `core/types.py`. Until the server runs, develop against `tests/fixtures/real_timeline_*.jsonl` fed in
from the browser console (no replay mode in the code).

## Follow-ups from machine 1 (do these first, Sat 00:15)
- Chat SLA is now on **time to first token**: show `ttft_p95_60s` against `policy.sla.chat_ttft_p95_s` (1.0 s)
  as the SLA tile, with total latency `p95_60s` beside it labelled "total (depends on reply length)".
  `policy.sla.chat_p95_s` no longer exists.
- `web/chat.html` should use `POST /api/chat/stream` (NDJSON deltas) so the reply appears as it is written.
- Snapshot now has `job_specs` (owner, deadline) and `quote` (null until Saturday): see HANDOFF.md.
- `Schedule.chat_busy_streams` is the chat traffic the plan assumed (null = full concurrency) and chat status has
  `busy_60s`; show both on the chat card so planned vs actual chat load is visible.

## Tasks, in order
1. **Dashboard** `web/index.html`, `web/app.js`, `web/style.css` (SPEC §10). Header: the claim ("When the
   grid runs short, the plan for AI data centers is diesel generators. This is the alternative.") + quote
   slot. Row 1: measured watts (big, "SoC power, measured by macOS powermetrics"), $/h at live price,
   gCO2/h at live mix, chat p95. Row 2: 24-h price + carbon curves with the schedule painted on (which job
   runs in which slot, device), current slot highlighted, feed age + STALE badge, "carbon curve: live mix
   held flat (proxy)" label when `carbon_curve_is_proxy`. Row 3: job cards (state, device, concurrency,
   progress, deadline, owner, measured rate). Row 4: event log (`grid` alerts, `event`, `plan`, `action`,
   `shortfall`, `approval`) + the solver's explanations. Controls: ISO picker (`iso_options`), objective
   (cost/carbon/balanced), DISPATCHER OFF toggle. Done when: on machine 1's `make demo`, every number
   updates live and shows its source/age.
2. **Phone pages** `web/chat.html` (POST `/api/chat`, shows reply + latency) and `web/owner.html` (the job
   owner's console: pending `ApprovalRequest`s from `GET /api/approvals?owner=` and `approval` WS events, a
   free-text reply box posting to `POST /api/approvals/{id}/reply`, the decision and the new schedule). `scripts/qr.py` → `make qr` prints QR codes for `PUBLIC_URL/chat` and `PUBLIC_URL/owner.html`.
   Done when: a phone on the same network chats and sees an owner request.
3. **Receipts screen** in the dashboard: renders machine 3's `Report` and comparison (baseline W, event W,
   % reduction, time-to-compliance, approvals with names/times, p95 before/during; dispatched vs dispatcher
   off: $, gCO2, deadlines met, watts under cap) and the audit trace list from `/api/trace`.
4. **Polish for a 4-minute demo**: legible from 1.5 m, no layout jumps, "agent offline" badge, empty and
   stale states that say what is missing rather than blank panels.

## Phase 2: when phase 1 is merged
5. **Operator console** `web/operator.html` (DEMO.md 1:15, "they're the utility"): a box to type or dictate
   (Web Speech API where available, shown as "transcript") → `POST /request`; show the readback, the one
   clarifying question if any, and the resulting schedule change. A paste box for OpenADR JSON →
   `POST /openadr/event`. Active cap events with a countdown and a **time-to-compliance counter** (seconds
   from event start until the 10-s rolling mean of measured watts is at or under the cap). "Ask" box →
   `POST /api/ask`. Done when: DEMO.md 1:15–2:30 is driven entirely from this page and the owner page.
6. **Shortfalls and approvals on the dashboard**: a shortfall shows the solver's two honest options (slip a
   deadline vs exceed the cap) with numbers; approvals list with who, what, when, decision; the operator's
   "approve going dark" posts `approve` to the approval route. Done when: DEMO.md 3:00 ("ask for 90%") reads
   clearly to someone who has never seen the app.
7. **Presentation polish**: projector contrast, legible at 1.5 m, driver hotkeys (D dispatcher toggle,
   1/2/3 objective, E event box, A ask box), a one-line "what you're seeing" caption per panel.
8. **Capture for the video**: 20-s screen captures of each DEMO.md beat from machine 1's live run; hand the
   files to machine 3 (link in your PR, not committed).
