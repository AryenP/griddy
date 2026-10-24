# K6: number audit against the evidence of record (09:15 run, DECISIONS 09:46)

Reviewer: machine 3 (Krish), Sat 14:30 PT, main at `997dd6a`. Scope per team/3-krish.md K6: README.md,
docs/devpost.md, DEMO.md, docs/demo-video.md, checked against DECISIONS 09:46 and the two reports it names:
`docs/evidence/compare-20261024-093434-vs-20261024-091909-baseline.md` (327 s) and
`docs/evidence/compare-20261024-093434-vs-20261024-092650-pause_all.md` (315 s).

## Mismatches, most severe first
1. **README.md:25 gives Brownout ✅ for "Deferred work still meets its deadline".** In the run of record
   Brownout's deadlines were 0/1 (both reports): train due to finish ~19 min after its deadline while the cap is
   held, and the owner is asked (D 09:46); ignoring the call met it (1/1). docs/devpost.md:59 states this plainly
   ("asks the owner about the ~19-minute slip"); the README table claims the opposite. Say "✅ or the owner is asked
   before it slips", which is what the run shows.
2. **The steps column mixes two windows.** README.md:48-50, docs/devpost.md:56-58, DEMO.md:42-43 and
   docs/demo-video.md:18 put ignore-the-call's 5899 steps (327-s window) beside Brownout's 1575 (315-s window, vs
   pause everything). Over the same 327 s as ignore-the-call, Brownout did 1625. The "315-327 s" caption covers it
   loosely; either show 1625 in the ignore row's comparison or add the window per row. "About 83 times the work of
   pausing everything" (1575 / 19) is correct, since those two share the 315-s window.
3. **DEMO.md 1:30 promises "measured watts drop under it, Within the cap" right after the judge chats (0:45).**
   With chat busy the Mac cannot get under a 30 % cut (D 10:00: busy chat alone is above it), and since b06cd51
   chat keeps full speed, so the plan goes to the operator instead. Either ask the judge to stop chatting before the
   1:10 request, or script the operator ask as the expected outcome while chat is busy. docs/demo-video.md:12 has
   the same promise.

## Checked and matching
| Number | Where | Source | Matches |
|---|---|---|---|
| ignore 20.85 W, 0 %, never, 5899 steps | README.md:48; devpost.md:56; DEMO.md:42; demo-video.md:18 | D 09:46; report vs baseline (327 s) | yes |
| pause everything 0.80 W, 99 %, 4 s, 19 steps | README.md:49; devpost.md:57; DEMO.md:42; demo-video.md:18 | D 09:46; report vs pause_all (315 s) | yes |
| Brownout 14.34 W, 93 %, 12 s | README.md:50; devpost.md:58; DEMO.md:43; demo-video.md:18 | both reports | yes |
| Brownout 1575 steps | same rows | report vs pause_all (315 s) | yes (see mismatch 2) |
| about 83 times the work | devpost.md:59; DEMO.md:43 | 1575 / 19 = 82.9 | yes |
| cap 15.10 W, 315-327 s from each cap start | README.md:43-44; devpost.md:52 | D 09:46 | yes |
| ~19-minute slip, owner asked | devpost.md:59 | D 09:46 | yes |
| chat-under-cap run: cap 19.68 W, mean 26.46 W, TTFT 0.20 s -> 4.56 s | devpost.md:88-90 | D 10:00; docs/evidence/20261024-094941.md | yes |
| two-policy runs 18.32/0.68 W, 21.18/1.64 W, 5 s/7 s | README.md:38-41; devpost.md:43-48 | D 02:28, D 03:10 (K3, unchanged) | yes |

Note from D 09:46: calibration 20261024-091539-calibrate read idle at 3.81 W (polluted); every number above is
measured watts or counted steps, not calibration, as D 09:46 says. No page or document claims chat keeps its SLA
under a cap (devpost.md:88-90 states the failed run; docs/qa Q13 rewritten in K11).
