# Rehearsal checklist

Two full cold-start rehearsals Saturday night with a teammate playing the judge, one more Sunday 9:30 AM.
Time each with a stopwatch; the judge sees four minutes (DEMO.md).

## Before each run (demo Mac)
- [ ] Wired or travel-router network up; `make probe` prints a CAISO price with today's timestamp.
- [ ] `make preflight` all PASS (or each WARN understood), then `make demo` from cold; dashboard up in under 2 minutes
      (no password with the pinned powermetrics rule from team/README.md; otherwise `sudo -v` in the same terminal).
- [ ] Ollama running with `OLLAMA_NUM_PARALLEL` matching chat max concurrency; `qwen3:4b-instruct` pulled (not plain `qwen3:4b`).
- [ ] Calibration under 12 h old on qwen3:4b-instruct (preflight checks it); evidence runs in docs/evidence/ current.
- [ ] `.env` has the LLM key and `APPLICATIONINSIGHTS_CONNECTION_STRING`; `telemetry.configure()` reports sinks `memory, azure-monitor`.
- [ ] Phones via QR (`make qr`): owner page, operator page; chat QR card on the table.
- [ ] Comparison runs exist (`make evidence`, or `make evidence3` for ignore / pause everything / Brownout).
- [ ] Application Insights open in a browser tab on Transaction search, last 30 minutes.

## The run (DEMO.md script)
- [ ] 0:00 diesel line and the operator quote on screen.
- [ ] 0:15 judge picks ISO and policy; schedule repaints; explanation readable.
- [ ] 0:45 chat from the phone (streamed); time-to-first-token p95 on screen against the 1.0 s SLA.
- [ ] 1:15 plain-text cut; read-back before anything moves.
- [ ] 1:45 owner refuses in words; watts stay under the cap while the operator decides; operator gets the
      solver's sentence and approves; only then do watts rise; time-to-compliance shows.
- [ ] 2:30 policy or ISO switch; Mac follows the new slot.
- [ ] 3:00 90 % ask; shortfall with the floor in watts.
- [ ] 3:30 `make report` and `make compare` render; one decision's trace shown in Application Insights.
- [ ] 3:50 close line.

## Failure drills (DEMO.md), each rehearsed once
- [ ] Grid feed down (pull the network): stale badge, plan marked "on last known data"; presenter says it.
- [ ] Ollama killed: chat page shows the error; everything else continues; presenter says it.
- [ ] LLM API key removed: "agent offline" badge; solver and controller continue; nothing pretends to be the agent.
- [ ] Infeasible ask: minimal relaxation shown, never a blank.
- [ ] Odd input from the judge: agent asks one clarifying question.
- [ ] Application Insights slow to ingest (it can take minutes): show the same spans from `/api/trace` and say Azure lags.

## After the last rehearsal
- [ ] Update the numbers in docs/devpost.md, docs/demo-video.md and the README proof table if the final
      evidence run differs (they come from docs/evidence/ reports, never typed).
- [ ] Record the video (docs/demo-video.md) from the same setup.
- [ ] Repo public or judges added; Devpost opt-ins per docs/devpost.md.

## Scripted cold start, Sat 24 Oct 04:48 PT (machine 1, run 20261024-044805, main at 279cfd5)
From nothing running (no runtime, no workloads, port 8080 free), `make demo`:

| Step | Seconds after `make demo` |
|---|---|
| first knob action (workloads paused at start) | 4.5 |
| first powermetrics sample | 7.5 |
| first live CAISO signal | 10.1 |
| first CP-SAT schedule | 11.6 |
| dashboard answering `/api/state` | 12.3 |

Every page (`/`, `/chat`, `/owner.html`, `/operator.html`, `/proof.html`) and every read route in HANDOFF.md
(`/api/state`, `/api/runs`, `/api/runs/{id}/series`, `/api/report`, `/api/compare` with both baselines,
`/api/trace`, `/api/approvals`, `/api/explain`) answered 200; a path in place of a run id answered 404.
`POST /api/ask` "Why is batch not running right now?" came back from the agent, grounded in the solver's facts
(batch planned for one slot at Sat 14:00-14:15, $4.98/MWh vs $34.45/MWh). The snapshot carried the trace's
`power_history`. Shutdown with Ctrl-C checkpointed the workloads and stopped the meter.
`make preflight` with the demo up: 13 PASS, 4 FAIL. Expected: ports 8080 and 8090 in use (the demo was running)
and no demo-stable tag at HEAD (cut after the final evidence run). Wrong: the sudo check tests `sudo -n true`,
which fails under the pinned powermetrics-only sudoers rule although the demo starts unattended, and the tag
hint says `git checkout demo-stable-1`, which would roll the demo back (Anuraag task 18).
