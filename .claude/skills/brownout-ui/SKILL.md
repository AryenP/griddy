---
name: brownout-ui
description: Brownout's own rules for every page in web/ (dashboard, chat, owner, operator, receipts). Use together with frontend-design whenever you build or change anything under web/. These rules win where they conflict with general design advice.
---

# Brownout UI rules

Use the `frontend-design` skill for the aesthetic direction; these rules are the brief and the constraints.

## The brief
- **Subject:** a grid-aware dispatcher for AI compute. Live electricity prices and fuel mix decide when each AI
  job runs; measured power proves it. The claim in the header: "When the grid runs short, the plan for AI data
  centers is diesel generators. This is the alternative."
- **Audience:** a Microsoft judge at a table, 1.5 m from a laptop screen (possibly a projector), for four
  minutes, plus the same judge on their own phone acting as a job owner or as the utility. Secondary: a data
  center operator who would use this daily.
- **Primary job of each page:** dashboard = see the grid, the measured watts and the plan move together;
  `/chat` = use the service and feel it is fast; `owner.html` = refuse or accept a deadline slip in words;
  `operator.html` = type the emergency and watch compliance happen; receipts = the numbers that prove it.
- **The moments that must read instantly (DEMO.md):** the measured watts dropping after a cap (time to
  compliance counting), the owner's refusal changing the plan, the solver's honest shortfall ("I can reach 22%,
  not 30%"), and dispatched vs dispatcher-off.
- **Vernacular to draw from:** grid operations and utility control rooms (load curves, interval data,
  dispatch instructions, frequency), not crypto or generic SaaS. One coherent design system across all pages:
  shared tokens in `web/style.css` `:root`, shared helpers in `web/common.js`.

## Non-negotiables (from CLAUDE.md; a page that breaks one is not done)
1. **Nothing simulated.** Every number is live or measured, from the API. No sample data, no placeholder
   numbers, no mock or replay mode in the code. Develop against `tests/fixtures/real_timeline_*.jsonl` fed into
   `window.brownout.handle(msg)` from the browser console only.
2. **Every number shows its source and age** ("measured by macOS powermetrics, 2 s ago"; "CAISO SP15 real-time,
   interval 01:40, feed 34 s old"). Label the kind: measured, planned (calibrated), attributed. A stale feed says
   STALE and the plan says "on last known data". An empty state says what is missing and why, never a blank.
3. **Escape everything from the server.** `textContent`, or the shared escaping helper before any `innerHTML`.
   Agent text (explanations, readbacks, approval messages) is untrusted.
4. **Contract exactly.** Field names from `core/types.py`, routes and events from HANDOFF.md. If something you
   need is missing, write it in the PR under "Needs from others"; do not invent fields or call other routes.
5. **Stack:** vanilla HTML/CSS/JS, no build step. Chart.js 4.4.1 from cdnjs only (pinned); no other external
   scripts. At most one webfont family from Google Fonts with a system fallback that still looks intentional
   (the venue network can drop). No host or port hardcoded: same-origin requests and `location.host` for `/ws`.
6. **Phone first for chat/owner/operator:** 375 px wide with no horizontal scroll, tap targets >= 44 px, the
   reply box reachable with the keyboard open. Visible keyboard focus, `prefers-reduced-motion` respected,
   WCAG AA contrast (projectors wash out low contrast).
7. **Motion only to show change:** the watts number when it moves, the plan when a slot flips, a decision
   arriving. No decorative entrance animations.
8. **Copy:** plain operator language, sentence case, active verbs ("Refuse", "Approve going over the cap").
   Errors say what happened and what to do. Never fake confidence: if the agent is offline, say "agent offline"
   and show the solver's facts.

## Done means
- `uv run pytest -q` passes, including `tests/test_web*.py` (ids used in JS exist in HTML, only contract routes
  called, pinned CDN, no hardcoded host/port, no unescaped `innerHTML`).
- `uv run python scripts/check_runtime.py` prints ok.
- Checked in a browser at 375 px and at 1440 px with the real fixtures; screenshots attached to the PR.
