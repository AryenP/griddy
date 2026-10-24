# 3 Krish: proof and production (receipts, telemetry, Azure, submission)

**Mission:** prove the result with numbers computed from timelines only, make the Microsoft stack real
(OpenTelemetry → Application Insights trace as the audit log), and own the submission.

**Owns:** `agent/reporter.py`, `scripts/compare.py`, `telemetry/**`, `infra/**`, `azure.yaml`, `docs/**`,
`README.md`, `config/isos.yaml`, `tests/test_report*.py`, `tests/test_compare*.py`, `tests/test_telemetry*.py`.

**Inputs:** timelines (`runs/<id>/timeline.jsonl`; real ones in `tests/fixtures/real_timeline_*.jsonl`).
Event kinds and fields: HANDOFF.md + `core/types.py`. **Output types:** `Report` in `core/types.py`.

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
