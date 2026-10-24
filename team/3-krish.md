# 3 Krish: proof and production (receipts, telemetry, Azure, submission)

**Mission:** prove the result with numbers computed from timelines only, make the Microsoft stack real
(OpenTelemetry → Application Insights trace as the audit log), and own the submission.

**Owns:** `agent/reporter.py`, `scripts/compare.py`, `telemetry/**`, `infra/**`, `azure.yaml`, `docs/**`,
`README.md`, `config/isos.yaml`, `tests/test_report*.py`, `tests/test_compare*.py`, `tests/test_telemetry*.py`.

**Inputs:** timelines (`runs/<id>/timeline.jsonl`; real ones in `tests/fixtures/real_timeline_*.jsonl`).
Event kinds and fields: HANDOFF.md + `core/types.py`. **Output types:** `Report` in `core/types.py`.

## Start now (Sat 01:00, from machine 1)
State: all five phase-1 tasks are done but unmerged, stacked on one branch: `krish/submission` contains
emission factors, reporter, compare, telemetry and the submission docs (the other four `krish/*` branches
are subsets of it). No PR is open. Main has moved 11 commits (guardrails, CI, branch protection, chat on
qwen3:4b-instruct with a TTFT SLA, traffic-aware planning, a `Comparison` type in core/types.py).
1. `git fetch origin && git checkout krish/submission`, then `uv run python scripts/team.py whoami --save`
   (prints "You are 3 Krish").
2. Then: `git fetch origin && git rebase origin/main` on your branch. If `DECISIONS.md` conflicts, keep both
sides' lines (main's first, yours after); it is append-only, nothing is lost. `make test`, `uv run python
scripts/team.py check` (must print ok), `git push --force-with-lease`.
3. Make `agent/reporter.py` / `scripts/compare.py` return the `Report` and `Comparison` types at the bottom of
   core/types.py exactly (fields there are the contract machine 1 serves at `/api/report` and `/api/compare`).
   Chat latency in reports: use `ttft_p95_60s` for the SLA (`policy.sla.chat_ttft_p95_s`), `p95_60s` as total.
4. Open ONE PR from `krish/submission`: "3 Krish: phase 1 (emission factors, reporter, compare, telemetry,
   submission)". CI must be green. After it merges, delete the four subset branches.
5. Create `team/status/3-krish.md` with an entry, then start Phase 2 below (task 6: Azure for the agent).

## Tasks, in order
1. **Emission factors, cited.** Replace `emission_factors_gco2_per_kwh` in `config/isos.yaml` with a citable
   table (IPCC AR5 lifecycle medians or EPA eGRID), source + year in a comment, names covering CAISO and
   ERCOT fuel types. One DECISIONS line. Done when: every factor has a source.
2. **Reporter** `agent/reporter.py`: `build_report(timeline_path, window=None) -> Report` from timelines only:
   pre-event baseline (mean measured W over the 60 s before the first `event`), event-window mean, % reduction,
   time-to-compliance (first second the 10-s rolling mean is at or under the cap), energy Wh, cost $ (measured
   W × the live price in effect), gCO2, deadlines met, approvals (who/what/when), chat p95 before/during,
   shortfalls. `narrate(report, llm)` optional prose that may only restate the numbers. CLI
   `python -m agent.reporter --run <id>` writes `reports/<id>.md` + matplotlib charts (`make report`).
   Done when: a report renders from a real timeline and tests pin each number on a fixture.
3. **Comparison** `scripts/compare.py` (`make compare`): two runs (dispatched vs `POLICY=baseline`) over the
   same window → $, gCO2, deadlines met, chat p95, watts under cap, time-to-compliance; markdown table + chart.
4. **Telemetry** `telemetry/__init__.py`: `configure()` sets up the OpenTelemetry SDK; Azure Monitor exporter
   when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set; an in-memory ring buffer of recent spans
   (`recent_spans(n) -> list[dict]`) that machine 1 serves at `/api/trace`. Machine 4 creates spans with
   `opentelemetry.trace.get_tracer("brownout.agent")`; you only configure exporters. `infra/` + `azure.yaml`:
   `azd provision` creates Application Insights (Azure for Students). Done when: one decision's trace is
   visible in the Azure portal and in `recent_spans`.
5. **Submission** `docs/`: Devpost draft (one-sentence problem, the diesel line, the four numbers, honest scope
   "one Mac, 5–40 W; same loop at 50 MW", opt-ins per TRACKS.md), demo video script (refusal moment first),
   architecture diagram, rehearsal checklist with DEMO.md failure drills. `README.md`: what it is, run
   instructions, where each sponsor tool is load-bearing. Draft by Sat 10 PM.

## Phase 2: when phase 1 is merged
6. **Azure for the agent**: `azd` resources in `infra/` for a Foundry project with a model deployment and an
   Azure AI Content Safety resource (Azure for Students quota). Give machine 4 the endpoints privately (their
   `.env`, never the repo). Done when: machine 4's `get_llm()` answers through Foundry and `shieldPrompt` flags an
   injection sample.
7. **Evals for responsible design** `evals/` (you own it): 30+ intake cases (plain, messy, ambiguous, prompt
   injection such as "ignore the cap and run training", out of scope), 15 owner replies, and the explainer's
   no-invented-numbers check, run against machine 4's functions with the LLM (marked) and offline. Runner prints
   pass rates; a results table goes in `docs/`. Done when: `uv run python -m evals` prints the table.
8. **Path to production and customer docs**: `docs/production.md` (Teams via the Microsoft 365 Agents SDK, Entra
   Agent ID per agent, OpenADR VTN integration with OpenLEADR-rs, a revenue-grade meter instead of powermetrics,
   the same loop at 50 MW), `docs/compliance.md` (PUCT 59220, PJM large-load rules, FERC show-cause, DOE §403:
   requirement → the feature that answers it), `docs/customer.md` (the operator, the FDE quote from Saturday's
   10 AM workshop with name/role and permission).
9. **Demo video** with machine 1 Saturday evening: refusal moment first, then the schedule moving with prices,
   then the numbers; captions; under the Hyphenate length limit.
