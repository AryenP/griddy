# K20: the README as a judge in 5 minutes

Machine 3 (Krish), Sat 22:15 PT, fresh clone of main at `1040599`. README.md only, five minutes. It is 2,058 words;
at a judge's reading pace five minutes covers roughly the top half: the intro, "Impact, from one replay", the
comparison table and "The proof so far". The rest (who controls what, the no-Mac block, sponsor tools, receipts) a
judge reaches only if they scroll.

## The four answers
1. **What Griddy is:** software that decides, slot by slot, which AI jobs on a machine run when the power grid is
   short, holds a utility's power cap within seconds, asks job owners before breaking a deadline, and proves it with
   the machine's own measured watts. Clear from the first paragraph.
2. **The one number I remember:** "about 372,000 people kept on" (Uri). It is the most memorable and the most
   estimated: a laptop's 61 % measured cut, credited at the 40 % the alert asked, applied to 4.1 GW of ERCOT large
   loads. Second: "about 83 times the work of pausing everything".
3. **Measured vs estimated:** measured = this Mac's watts, the time to compliance, the training steps, chat latency;
   live = ISO prices and mix; recorded = the EIA-930 data the replays use; estimated = anything at grid scale (MW freed,
   people), labelled. Clear, and stated twice.
4. **What I would ask:** "Would a real data center's large loads cut 40 % in seconds the way a laptop does? Who is the
   customer, and did one tell you they want this?" (no customer voice anywhere in the README); "Which Microsoft piece
   runs today?" (see below).

## Sentences I had to read twice
1. Impact: "Credited only as far as the grid asked (40 %) and applied to ERCOT's large loads (up to 4.1 GW, the sum of
   each one's own monthly peak), that frees up to 1,653 MW". Three qualifications in one clause; split it: "The Mac
   cut 61 %. We count only the 40 % the grid asked for. Applied to ERCOT's 4.1 GW of large loads, that is 1,653 MW."
2. "1575 (315 s; 1625 over ignore's 327 s)" in the policy table, and "315-327 s from each cap start" above it.
3. "planned ✅" in the first proof table's Deadline column: planned by whom, met or not?
4. "Against the honest naive policy too": "honest naive" needs a word of explanation (= pause everything, done
   properly).

## Terms not explained (in the first five minutes)
CP-SAT; ISO; EEA 3; EIA-930; OpenADR 3.1; SoC power; "slot"; "cap"; "time to compliance" (defined only in Receipts,
near the end); "DECISIONS 18:38" (a reader does not know DECISIONS.md is a timestamped build log until the bottom);
"large loads"; "non-simultaneous" (Devpost says it, README does not).

## Reads as running, but is not (tonight)
1. **"Where each sponsor tool is load-bearing", first row: "Microsoft Agent Framework + Foundry (agent/llm.py; Claude
   behind the same interface otherwise)".** Every live run used Claude Sonnet 5.5; the Foundry path has never run
   against a deployment. docs/devpost.md now says so (line 141-142); the README does not.
2. **Same table: "OpenTelemetry → Azure Application Insights ... The audit log".** Not connected in this build
   (devpost.md:131-133 now says "it is not connected in this build"; spans are in /api/trace). The README's "Run it"
   paragraph says spans stay in /api/trace without the string, but the table reads as running.
3. **Comparison table: "Flexible work moves to cheap, clean hours every day ✅ live prices + fuel mix".** The carbon
   curve is the live mix held flat for the day (D 22:50, `carbon_curve_is_proxy`; devpost.md "Honest scope" says
   "only price varies across slots"). So the solver can move work to cheap hours, but it cannot tell clean hours
   apart. Say "cheap hours (live prices; carbon is today's live mix, held flat)".
