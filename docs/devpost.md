# Devpost draft: Brownout

Draft for the Cal Hacks 13.0 submission (due Sun 25 Oct, 8:50 AM PT). Every "to be measured" is filled
from the demo Mac's own runs (`make report`, `make compare`) after the final rehearsal; none is typed
from memory. Measured numbers below come from DECISIONS.md; dated facts under "Why now" are cited in
RESEARCH.md. Remove this paragraph before submitting.

## Tagline
When the grid runs short, the plan for AI data centers is diesel generators. This is the alternative.

## The problem (one sentence)
When the grid is short of power, operators have two crude options for AI compute, run everything or
switch to diesel, because nothing decides which work can wait, asks the people who own it, and proves
the result in watts.

## Why now
- Winter Storm Fern (Jan 2026): the federal response for data centers was to order them onto backup
  generators, citing 35 GW of diesel; no request to shed compute was reported (Fortune, 4 Feb 2026).
- Texas PUCT Docket 59220 (24 Jul 2026): co-located data centers must fully curtail on ERCOT instruction.
- PJM Board (16 Jan 2026): new large loads of 50 MW or more are curtailed before pre-emergency demand response.
- EPRI DCFlex: 10–30 % peak-reduction potential from flexible data centers (Reuters, 8 Oct 2026).

## What it does
Brownout is a grid-aware compute dispatcher. It reads the live grid (CAISO and ERCOT prices, day-ahead
curve, load forecast, fuel mix, alerts) with the timestamp and age of every number, schedules each AI
job over the next 24 hours with a CP-SAT solver against cost, carbon, deadlines and a chat SLA
(time to first token p95 <= 1.0 s, replies streamed), executes the current slot on a real machine (pause/resume with checkpoints, concurrency, GPU vs CPU),
and measures the result with macOS `powermetrics`, which is independent of our code.

When a utility asks for a cut, in OpenADR JSON or plain words, the agent reads it back, the solver
re-plans, and if a deadline would slip the job's owner is asked on their phone. They can refuse in their
own words ("this has to finish by 9 AM Monday") and the solver re-plans around the refusal, saying
exactly how much of the cut it can still deliver. If the ask is impossible, it says so and shows the
minimal relaxation instead of pretending.

## The four numbers (measured on the demo Mac, from timelines)
| | Value | Source |
|---|---|---|
| Power reduction during the event | to be measured (`reduction_pct`, `baseline_w` → `event_w`) | `make report` |
| Time to compliance (10-s mean at or under the cap) | to be measured (`time_to_compliance_s`) | `make report` |
| Cost vs dispatcher off, same window length | to be measured (`delta.cost_usd`) at the live price | `make compare` |
| Carbon vs dispatcher off, same window length | to be measured (`delta.co2_g`) at the live fuel mix | `make compare` |

Already measured on the demo Mac (Fri 23 Oct, DECISIONS.md): idle 1.35 W; training +19.5 W on GPU,
+13.0 W on CPU; batch embeddings +22.8 W on GPU; chat +24.8 W at concurrency 4, measured on plain
qwen3:4b before the switch to qwen3:4b-instruct (chat watts on the instruct model: to be measured). The
solver put training in Saturday 14:00–16:00 at an average $5.32/MWh against $36.33/MWh in the slots it
skipped (CAISO SP15 day-ahead, live), solved OPTIMAL in 0.06 s. A 15 W cap at the 23:45 slot boundary:
measured 18.5 W → 2.17 W at 23:45:04, under the cap within ~4 s, with no input after the cap was posted.

## Honest scope
One MacBook (Apple M2 Pro), roughly 1–30 W. The feeds, the solver, the approvals and the audit trail
are the same loop at 50 MW; the knobs at that scale are cluster schedulers and power caps instead of a
process on a laptop. Watts are SoC power (CPU + GPU + ANE) as `powermetrics` reports it, not a wall
meter. The 24-hour carbon curve is the live mix held flat (only price varies across slots), and the
dashboard says so. Chat total latency p95 measured 9.67 s at concurrency 4 with 256-token replies on
Friday night (plain qwen3:4b), against the 2 s SLA we had written down. We changed the promise, not the measurement:
replies stream, and the SLA is time to first token p95 <= 1.0 s. On qwen3:4b-instruct the worst TTFT
p95 measured 0.29 s idle and 0.24 s with training on the GPU; total p95 for 256 tokens is 5.0–8.9 s
idle and 8.3–15.7 s with training, reported beside it and not promised.

## Responsible design
- The solver decides, the LLM explains and negotiates, the controller executes. The LLM has no code
  path to any knob.
- Nothing simulated reaches the screen: every price, watt and dollar is live or measured, with source and age.
- A human owner approves any deadline slip; refusals are respected and logged with name and time.
- Every agent call is an OpenTelemetry span, exported to Azure Application Insights when configured:
  the audit log.
- Plain requests and owner replies are parsed by rules, not the LLM; any LLM sentence that contains a
  number not in the solver's facts is replaced by the facts verbatim.
- If the LLM is down, the solver and controller keep running and the UI says "agent offline".

## How we built it
Python 3.11, FastAPI, OR-Tools CP-SAT, gridstatus (CAISO, ERCOT), powermetrics, Ollama with
qwen3:4b-instruct (chat, streamed), PyTorch MPS (training with checkpoints), sentence-transformers
(batch embeddings), Microsoft Agent Framework with Foundry for the agent layer when Azure is configured
(Claude behind the same interface otherwise), OpenTelemetry with the Azure Monitor exporter, Application Insights
provisioned with `azd`, vanilla JS + Chart.js dashboard. Emission factors: IPCC AR5 lifecycle medians.

## Challenges
- macOS 15 `powermetrics` prints GPU power twice per sample; the meter splits on sample headers.
- PJM needs an API key (`PJM_API_KEY`); CAISO and ERCOT are keyless and are what we demo.
- Plain `qwen3:4b` always thinks and leaked its reasoning into replies; chat runs on qwen3:4b-instruct.
- Venue bandwidth: model downloads at ~145 KB/s.

## What's next
Microsoft Entra Agent ID for the agent, approvals in Teams, an OpenADR 3.1 VEN against a real VTN,
and the same loop on a GPU cluster where the knobs are power caps and the scheduler.

## Prize opt-ins (TRACKS.md)
Microsoft Challenge · Most Technically Advanced Hack · Best Planet-First Social Impact · Hyphenate
(demo video). Fetch.ai only if the three-agent ASI:One flow was built. Nothing else.

## Links
Repo: https://github.com/AryenP/abc (make public or add judges before submitting) · Demo video: ⟨link⟩
