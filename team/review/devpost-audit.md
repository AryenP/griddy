# K19: Devpost claim audit

Machine 3 (Krish), Sat 22:10 PT. Fresh clone of main at `cd3e608`; `docs/devpost.md` read top to bottom (165 lines).
Sources: **V** = recomputed by `scripts/verify.py` from docs/evidence/runs/ (74 of 74 pass in this clone, 14 of them
quoted from devpost.md); **D hh:mm** = DECISIONS.md; **E** = a docs/evidence/ file; **R** = RESEARCH.md; **PDF** = a cited
report page (checked in K15).

## Mismatches and claims to fix, most important first
1. **devpost.md:120-121, eval counts are stale.** "16 of 16 prompt-injection evals are rejected offline ... (121-case
   suite, docs/judging/evals.md, 05:51)". docs/judging/evals.md (regenerated 21:57) has 138 cases, **19 of 19**
   injections, 116 pass / 0 fail / 22 need an LLM. Say "19 of 19 ... (138-case suite, docs/judging/evals.md)".
2. **devpost.md:124-125, Application Insights.** "Every agent call is an OpenTelemetry span, exported to Azure
   Application Insights when configured: the audit log." Tonight it is not connected (team/status/1-aryen.md, Sat
   21:45: the connection string is not in .env, so the app exports no spans). "When configured" is literally true, but
   "the audit log" reads as running. Say what is true now: spans are recorded in the app (/api/trace); Application
   Insights is provisioned (azd) and connects with one .env line, not connected for the demo, unless Aryen connects it.
3. **devpost.md:133-135, Agent Framework and Foundry.** "Microsoft Agent Framework with Foundry for the agent layer
   when Azure is configured (Claude behind the same interface otherwise), OpenTelemetry with the Azure Monitor
   exporter, Application Insights provisioned". The Foundry path exists in code (agent/llm.py:107-122) but Azure is not
   configured tonight; every live run in this repo (D 02:25, the 02:33 and 20:33 live evals) ran on Claude Sonnet 5.5.
   A judge will read "built with Microsoft Agent Framework" as what ran. Say: "the agent runs on Claude Sonnet 5.5
   through the Anthropic SDK; the Microsoft Agent Framework + Foundry path is built behind the same interface and has
   not been run against a Foundry deployment."
4. **devpost.md:101, "not in the report itself" is now false.** docs/evidence/20261024-140239.md:31 now says "load
   outside the plan up to 11.55 W was measured and counted against the cap (9 re-solve(s) for it)". Cite the report.
5. **devpost.md:161, Fetch.ai opt-in.** "Fetch.ai only if the three-agent ASI:One flow was built." One read-only agent
   was built (D 17:11: "The optional second agent ... is not built"). Decide and write it: opted in with the one agent
   (and say so), or not opted in. TRACKS.md's condition (three agents, primary workflow in ASI:One) is not met.
6. **devpost.md:80-81, "up to about 2 % of ERCOT's live demand".** From D 14:53's live check (1,289 MW of 62.2 GW =
   2.1 %). The share depends on when you look: at ERCOT's night demand (~45 GW) the same 1.3 GW is ~2.9 %, so "up to"
   is the wrong bound. Say "about 2 % of ERCOT's demand at 2:53 p.m. Saturday (the dashboard shows it live)".
7. **devpost.md:44, 21.57 W has no written source.** It is derived (the 15.10 W cap is 30 % below it, D 03:10) and
   correct, but no DECISIONS line or report states it; 96 % / 92 % and 17.68 W are fine (D 02:28, E).
8. **Differs from README.md:** the README's "Impact, from one replay" (Uri: 28.2 W -> 10.9 W measured, credited at the
   40 % asked, up to 1,653 MW, about 8 % of 20,000 MW shed, about 372,000 people; D 18:38) is not in the Devpost at
   all, while the Devpost's grid-scale paragraph uses the 31 % evidence-run cut (1.3 GW). Both are sourced; the
   organizers asked for impact in lives and money, and the README's sentence is the one that answers it.
9. **Not claims, but before submitting:** remove lines 3-6 (the draft note); fill the demo video link (line 165); the
   repo is still private ("make public or add judges").

## Every number, with its source
| Line | Number | Source | Status |
|---|---|---|---|
| 18 | 35 GW of diesel; Fortune 4 Feb 2026 | R "The bold claim" | ok |
| 19 | PUCT 59220, 24 Jul 2026 | R "Why a utility can order this" | ok |
| 20 | PJM Board 16 Jan 2026, 50 MW | R | ok |
| 21 | EPRI DCFlex 10 to 30 %, Reuters 8 Oct 2026 | R | ok |
| 27 | TTFT p95 <= 1.0 s | config policy.sla.chat_ttft_p95_s; D 00:15 | ok |
| 37 | cap 30 % below baseline, 5 min, training due 2 h | D 02:28, D 03:10 | ok |
| 43 | 0.68 / 1.64 W; 18.32 / 21.18 W | V | ok |
| 44 | 96 % / 92 %; 17.68 W; 21.57 W | E, D 02:28; 21.57 derived (mismatch 7) | ok / see 7 |
| 45 | 5 s / 7 s; never | V | ok |
| 46 | 99 % / 99 %; 0 % / 0 % | V | ok |
| 47 | 0.054 / 0.132 Wh; 1.524 / 1.761 Wh | E (both compare reports) | ok (not in V) |
| 48 | 0.017 / 0.043 g; 0.493 / 0.573 g | E | ok (not in V) |
| 52 | 315-327 s; cap 15.10 W | V (cap_w 15.102); D 09:46 | ok |
| 56-58 | 20.85 W, 0 %, 5899; 0.80 W, 99 %, 4 s, 19; 14.34 W, 93 %, 12 s, 1575, 1625 | V | ok |
| 60 | about 83 times; ~19-minute slip | 1575 / 19 = 82.9; D 09:46 | ok |
| 61 | void attempts | D 04:25, D 08:00 | ok |
| 63-64 | idle 0.51 W; chat +25.6 W; train +22.9 W at 18.3 steps/s, +13.3 W at 4.8; batch +24.1 W | D 03:10 | ok |
| 65-66 | $5.32 vs $36.33/MWh; OPTIMAL 0.06 s; ERCOT 0.04 s | D 23 Oct 23:15; D 00:35 | ok |
| 67 | 18.5 W -> 2.17 W in ~4 s; 17.5 W | D 23:45; D 00:00 (17.50 W) | ok |
| 70-73 | 8.9 W of 17.7 W, 02:36-04:36; 12.55 W; 0.4 W | E demo-flow-live-20261024.md:16-20 | ok |
| 78-79 | 4,132 MW; 9,456 MW; PDF p. 9; 474 GW; 90 %; 5 Aug 2026 | PDF (K13: checked) | ok |
| 80 | 31 %; about 1.3 GW | 1 - 14.34 / 20.85 = 31.2 % (V); 4,132 x 0.312 = 1,289 MW | ok |
| 81 | up to about 2 % of live demand | D 14:53 (one moment) | mismatch 6 |
| 85 | 0.5 W idle to 26 W | D 02:28 (0.39 W, +26.25 W), D 03:10 (0.51 W) | ok |
| 89-90 | 9.67 s at concurrency 4, 256 tokens; 2 s SLA | D 23 Oct 23:14 | ok |
| 91-93 | 1.0 s; 0.29 s / 0.24 s; 5.0 to 8.9 s; 8.3 to 15.7 s | D 00:22 | ok |
| 95-96 | 19.68 W; 26.46 W; 0.20 s -> 4.56 s | V | ok |
| 98 | 0.08 s | V | ok |
| 100 | 8 s; 84 %; 47 %; 0.19 s | V; 84 % per D 15:15's correction | ok |
| 101 | "not in the report itself" | E 20261024-140239.md:31 now has it | mismatch 4 |
| 112-115 | HVE Core review; who may act | D 14:45; D 20:24 (separate tokens) | ok |
| 120-121 | 16 of 16; 121-case suite | docs/judging/evals.md: 19 of 19, 138 cases | mismatch 1 |
| 121-123 | 135 of 138; 19 of 19; 14 of 14; 86 of 90 | E evals-live-20261024-2033.md:15-21; E evals-live-20261024.md | ok |
| 135 | no chart library | web/*.html load no external script | ok |
| 144 | ~145 KB/s | D 23 Oct 23:25 | ok |
| 149-151 | 4.5 s late; 1, 2, 4 streams | D 10:00 (4.56 s), D 10:09 | ok |

No number in docs/devpost.md is without a source. Numbers recomputed by `verify.py`: every mean, share-of-seconds,
time to compliance, step count and chat latency; not recomputed (report or DECISIONS only): energy, carbon, the
calibration deltas, the solver timings and prices, the 23:45 boundary, the demo-flow numbers.
