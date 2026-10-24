# Rehearsal checklist

Two full cold-start rehearsals Saturday night with a teammate playing the judge, one more Sunday 9:30 AM.
Time each with a stopwatch; the judge sees four minutes (DEMO.md).

## Before each run (demo Mac)
- [ ] Wired or travel-router network up; `make probe` prints a CAISO price with today's timestamp.
- [ ] `sudo -v` in the same terminal, then `make demo` from cold; dashboard up in under 2 minutes.
- [ ] Ollama running with `OLLAMA_NUM_PARALLEL` matching chat max concurrency; `qwen3:4b-instruct` pulled (not plain `qwen3:4b`).
- [ ] `make calibrate` re-run on qwen3:4b-instruct (chat watts were measured on the old model).
- [ ] `.env` has the LLM key and `APPLICATIONINSIGHTS_CONNECTION_STRING`; `telemetry.configure()` reports sinks `memory, azure-monitor`.
- [ ] Phone on the owner page via QR (`make qr`); chat QR card on the table.
- [ ] A dispatcher-off run of the same length exists for `make compare` (`make baseline`).
- [ ] Application Insights open in a browser tab on Transaction search, last 30 minutes.

## The run (DEMO.md script)
- [ ] 0:00 diesel line and the operator quote on screen.
- [ ] 0:15 judge picks ISO and policy; schedule repaints; explanation readable.
- [ ] 0:45 chat from the phone (streamed); time-to-first-token p95 on screen against the 1.0 s SLA.
- [ ] 1:15 plain-text cut; read-back before anything moves.
- [ ] 1:45 owner refuses in words; re-plan states the reachable %; watts drop; time-to-compliance shows.
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
- [ ] Fill every "to be measured" in docs/devpost.md and docs/demo-video.md from that run's `reports/*.md`.
- [ ] Record the video (docs/demo-video.md) from the same setup.
- [ ] Repo public or judges added; Devpost opt-ins per docs/devpost.md.
