# K3: number audit across what judges read

Reviewer: machine 3 (Krish), Sat 06:05 PT, main at `deda373`. Every number in `README.md`, `docs/devpost.md`,
`docs/judging/*.md` and `docs/evidence/*.md`, checked against the `DECISIONS.md` line (**D hh:mm**) or evidence
report it cites. Evidence reports are the sources for the other files; they were checked against D 02:28,
D 03:10 and the run ids in their names. Re-run after the final evidence run (D 04:25: scheduled 06:40), when
README and Devpost numbers change.

## Mismatches (most severe first; one issue each, pending until `gh` works on machine 3)
1. **"Nothing simulated" is now false.** `README.md:10` "Nothing is simulated: every price, watt and dollar on
   screen is live or measured" and `docs/devpost.md:82` "Nothing simulated reaches the screen" contradict
   D 05:45 (a simulated neighbourhood line, diesel and 20 data centers on screen since 05:35). A judge reading
   the repo after the demo would see the claim broken. Say what is simulated and that it is labelled.
2. **Stale three-policy numbers.** `docs/judging/criteria.md:23` gives the first pass (D 03:55: Brownout 13.96 W,
   69 % under the cap, 1562 steps; pause all 2.09 W, 97 %, 17 steps) and `criteria.md:28` says the re-run is
   "to be measured". It was measured: D 04:25 (ignore 21.40 W, 0 %, 5670 steps; pause all 1.54 W, 99 %, 16 steps;
   Brownout 1.26 W, 99 %, 35 steps, compliant in 5 s). Same stale line in `docs/judging/compliance.md:14`
   ("69 %"). D 04:25 also says neither pass is the evidence of record; the 06:40 run is.
3. **`docs/devpost.md:51-52`** says `make evidence3` "is running; its numbers go here when it finishes". It
   finished twice (D 03:55, D 04:25); the run of record is the 06:40 one (D 04:25).
4. **"Chat stays usable during a cap" is not what the source measured.** `docs/judging/criteria.md:24` cites
   D 00:22 (a chat sweep, idle and with training, no cap) and D 01:50 (three live users, no cap). No recorded
   run has chat traffic while a cap is in force (both evidence comparisons show chat p95 "n/a").
5. **Scope ranges disagree.** `README.md:106` and `docs/devpost.md:69`: "roughly 1-30 W";
   `docs/judging/criteria.md:29` and `docs/judging/production.md:3`: "about 0.5 W idle to about 25 W per job".
   Sources: idle 0.39 W (D 02:28) and 0.51 W (D 03:10); the largest single-job delta +26.25 W (chat, D 02:28).
   Pick one wording from D 03:10.

## Checked and matching
| Number | Where | Source | Matches |
|---|---|---|---|
| 18.32 W / 0.68 W, 0 % / 99 %, never / 5 s | README.md:37-38; devpost.md:43-46; criteria.md:22 | D 02:28; docs/evidence/compare-20261024-022026-vs-20261024-021247-baseline.md | yes |
| 21.18 W / 1.64 W, 0 % / 99 %, never / 7 s | README.md:39-40; devpost.md:43-46; criteria.md:21; compliance.md:12; customer.md:25 | D 03:10; docs/evidence/compare-20261024-025349-vs-20261024-024609-baseline.md | yes |
| 96 % (17.68 -> 0.68 W) | devpost.md:44 | D 02:28 (17.68 W baseline); 0.68 W evidence | yes (1 - 0.68/17.68 = 96.2 %) |
| 92 % (21.57 -> 1.64 W) | devpost.md:44 | D 03:10 cap 15.10 W = 30 % below baseline, so baseline 21.57 W; not written in D | yes, derived; state the baseline in D or the report |
| 0.054 / 0.132 Wh, 1.524 / 1.761 Wh, -92 % | devpost.md:47; criteria.md:21 | both evidence reports; D 03:10 | yes |
| 0.017 / 0.043 g, 0.493 / 0.573 g | devpost.md:48 | both evidence reports | yes |
| idle 0.51 W; chat +25.6 W; train +22.9 W GPU at 18.3 steps/s, +13.3 W CPU at 4.8 steps/s; batch +24.1 W | devpost.md:54-55 | D 03:10 (0.51, 25.58, 22.85, 18.25, 13.28, 4.81, 24.11) | yes (rounded) |
| $5.32 vs $36.33/MWh, OPTIMAL 0.06 s | devpost.md:56-57; criteria.md:55 | D 23:15 (M3) | yes |
| ERCOT solved in 0.04 s | devpost.md:57 | D 00:35 | yes |
| 18.5 W -> 2.17 W within ~4 s; back to 17.5 W | devpost.md:57-58; criteria.md:20 | D 23:45; D 00:00 (17.50 W) | yes |
| 8.9 W of 17.7 W; over the cap by up to 12.55 W; lowest 0.4 W | devpost.md:61-64 | docs/evidence/demo-flow-live-20261024.md:16-20 | yes |
| TTFT p95 0.29 s idle / 0.24 s training; total 5.0-8.9 s idle, 8.3-15.7 s training; SLA 1.0 s | devpost.md:75-77; criteria.md:24; README.md:99 | D 00:22 | yes |
| 9.67 s total p95 at concurrency 4, 256 tokens | devpost.md:73 | D 23 Oct 23:14 | yes |
| first token <= 0.17 s for 3 live users | criteria.md:24 | D 01:50 | yes (but see mismatch 4: no cap) |
| $48.67721 = $48.67721 | criteria.md:25 | D 23:15 (M1) | yes |
| 74 pass / 0 fail / 16 need LLM; injection 12/12 | docs/judging/evals.md:19 | `python -m evals` re-run on main at 06:00: same | yes |
| 86 / 90 live; 4 failures | devpost.md; evidence/evals-live-20261024.md:19 | that file (verbatim run output, 02:33) | yes |
| 35 GW diesel, Fortune 4 Feb 2026 | devpost.md:18 | R "The bold claim" | yes |
| PUCT 59220 24 Jul 2026, 30-min, >= 60 min notice; SB6 >= 75 MW; PJM 16 Jan 2026 >= 50 MW; FERC 18 Jun 2026; DOE §403 | devpost.md:19-20; compliance.md:9-12; production.md:29 | R "Why a utility can order this" | yes |
| EPRI DCFlex 10-30 % (Reuters 8 Oct 2026) | devpost.md:21; criteria.md:10; compliance.md:14; production.md:30 | R "Why a utility can order this" | yes |
| Emerald AI 25 % for 3 h; OpenAI 1 GW of 3.2 GW | production.md:31 | R "Prior art" | yes |
| cap 30 % below the measured baseline, 300 s | README.md:31; devpost.md:37; criteria.md:21 | D 02:28, D 03:10 | yes |

## Simulated presented as measured?
No simulated number appears in README.md, docs/devpost.md, docs/judging/ or docs/evidence/ (searched for
"neighbourhood", "simulated", "diesel avoided"). The only problem is the opposite one: mismatch 1 claims nothing
is simulated at all.
