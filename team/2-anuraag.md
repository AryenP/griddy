# 2 Anuraag: frontend (everything the judge sees and touches)

**Mission:** the dashboard is the pitch; there are no slides. A judge must read the live grid, the
measured watts and the schedule at a glance, and act from their phone.

**Owns:** `web/**`, `scripts/qr.py`, `tests/test_web*.py`. Vanilla HTML/JS/CSS + Chart.js (pin an exact
CDN version). No build step. Must work at phone width.

**Talks to:** machine 1's API (HANDOFF.md contract; `/ws` + `/api/*`). Field names are the pydantic models
in `core/types.py`. Until the server runs, develop against `tests/fixtures/real_timeline_*.jsonl` fed in
from the browser console (no replay mode in the code).

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
   owner's console: pending approval requests, free-text reply box; routes in HANDOFF.md once machine 1
   adds them). `scripts/qr.py` → `make qr` prints QR codes for `PUBLIC_URL/chat` and `PUBLIC_URL/owner.html`.
   Done when: a phone on the same network chats and sees an owner request.
3. **Receipts screen** in the dashboard: renders machine 3's `Report` and comparison (baseline W, event W,
   % reduction, time-to-compliance, approvals with names/times, p95 before/during; dispatched vs dispatcher
   off: $, gCO2, deadlines met, watts under cap) and the audit trace list from `/api/trace`.
4. **Polish for a 4-minute demo**: legible from 1.5 m, no layout jumps, "agent offline" badge, empty and
   stale states that say what is missing rather than blank panels.
