# K5: after-the-fact review of what merged at 06:10

Reviewer: machine 3 (Krish), Sat 06:23 PT, main at `686767b`. Merged at 06:10: #15 preflight fixes, #17 style
cleanup, #18 evals, #19 accessibility, #20 operator neighbourhood replay, #21 architecture picture, #22 driver card
(plus machine 4's status). Each branch was tested by machine 3 before the merge (06:02 pass): tests green,
`scripts/team.py check` ok, `scripts/check_runtime.py` ok, merged cleanly. On main now: `pytest -q` 359 passed,
2 skipped (Windows; tests/test_meter.py excluded, it imports fcntl); check_runtime ok.

## Findings, most severe first
1. **HIGH (time-sensitive): the demo tag the driver card sends you to is Friday's build.**
   `docs/judging/driver-card.md` step 1 says the demo runs from the newest `demo-stable-N` tag, and preflight now
   FAILs unless HEAD is on one. The only tag, `demo-stable-1` (84b7afc, Sat 01:17), is 147 commits behind main and
   has none of `web/operator.html`, `web/owner.html`, `web/proof.html`, `agent/reporter.py`, `telemetry/` or
   `neighbourhood/`. Following the card today would demo a build that cannot run DEMO.md 1:15-3:30.
   `make tag-stable` has been the "next" step in team/status/1-aryen.md since the 00:40 entry (repeated in three
   later entries). Tag after the 06:40 run and a full rehearsal, and before anyone walks to the table.
2. **MEDIUM: injection numbers are stale after #18.** The suite grew from 90 to 121 cases, injection from 12 to 16
   (offline 16/16, all by rules; total 100 pass / 0 fail / 21 need LLM, matching docs/judging/evals.md). Still
   saying 12: docs/devpost.md ("12 of 12 prompt-injection evals") and docs/qa/judge-questions.md Q10 (machine 3's;
   fixed on krish/k2-judge-questions). "86 of 90 live" is the 02:33 run of the old suite
   (docs/evidence/evals-live-20261024.md); a live run of the 121-case suite is not recorded.
3. **MEDIUM: the driver card's 3:30 shows one decision in Application Insights; that has not been verified.**
   team/status/1-aryen.md (04:49 and the next entry) still lists "verify spans reach Application Insights once .env
   has the string". The card's fallback (`/api/trace?n=50`) works; verify the portal before the table or make the
   fallback the plan.
4. **LOW (K1 finding 6): #20 "Stop the replay"** reports "replay stopped" while the real cap it issued stays in
   force for up to two minutes.

## Checked and passing
- **#20 operator page, simulated labels:** the panel sits under a SIMULATED badge; every simulated readout (clock,
  line loading, diesel kW, diesel kWh, "avoided") says "(simulated)"; "Our sites" says "(measured)"; the page
  accepts only events with `simulated: true` (K1 addendum). Machine 1's dashboard panel (4beb598) tags each part
  simulated or measured as well.
- **#21 architecture picture:** the LLM layer (intake, negotiation, explanations) has arrows only to the solver
  ("cap / policy", "decision") and from it ("shortfall", "facts"); the only arrow into Knobs comes from the
  Executor; the picture says "agent/ returns data only: no code path to the executor or a knob". The neighbourhood
  is a dashed box labelled SIMULATED. The LLM box says "Microsoft Agent Framework / Foundry, or Claude"; the model
  running today is Claude Sonnet 5.5 (D 02:25), which "or Claude" covers.
- **#22 driver card, promises vs code:** every hotkey exists (dashboard D, 1, 2, 3, R at web/app.js:573; operator
  E, A, N at web/operator.js:353); the Grid select, `/proof.html` with "Show these runs", `make preflight`,
  `make qr` and `make tag-stable` exist. 3:00 "the floor with chat protected, in watts, from the solver" matches
  the live run (docs/evidence/demo-flow-live-20261024.md: "the lowest the plan goes while the cap holds is 0.4 W").
  The card tells the driver never to say a number that is not on screen, never to paraphrase a quote, and to call
  the neighbourhood simulated before showing it.
- **#15 preflight:** the sudo probe runs exactly the Makefile's pinned powermetrics line once (`-n 1`) and only
  reads; the demo-tag check now says "tag this commit once the rehearsal passes", consistent with finding 1.
- **#18 evals:** the new cases (claimed grants, bare hours, operator questions that try to steer a knob) all pass
  offline; `operator_ask` 15/15.
- **#17 style cleanup, #19 accessibility:** tests pass (AA contrast test over the style tokens, keyboard order).
