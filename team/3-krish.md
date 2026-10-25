# 3 Krish: supervisor

## NEW (Sat 05:45): your queue for the next hours, in order. Machine 4 (Arumalla) now does the 10-minute checks
Aryen asked for you to have work. You still never edit machine 1's or 2's code: you review, verify and write
your own files (`team/review/**`, `docs/qa/**`, your status file). Real bugs go in GitHub issues titled
`[supervisor] ...` with file, line, what you expected, what you saw. Branch `krish/<task>`, then a pull request.
Since 05:35 part of the demo is SIMULATED by Aryen's decision (DECISIONS 05:45): read that entry first.

### K1. Deep review of the two new pieces (about 45 min)
`fleet/agent.py`, `fleet/hub.py`, `neighbourhood/model.py`, and their wiring in `controller/execute.py`,
`api/app.py`, `api/routes.py` (DECISIONS 05:10-05:45, HANDOFF.md). Look for real failures, for example:
a laptop that drops out while a cap is in force; a laptop that is plugged in; the neighbourhood's call for a cut
when our sites are idle (their baseline is tiny, so their "response" cannot move); the time-lapse ending while a
cap is still in force; a simulated number that reaches a page or a report without "simulated"; anything that
changes the single-Mac behaviour when no laptop and no neighbourhood are configured. Run `uv run pytest -q`.
Write `team/review/0545-fleet-neighbourhood.md` (findings, most severe first, each with file:line) and open an
issue for each real bug. Done when: the review is merged and every finding has an issue or a "not a bug" line.

### K2. The judges' hard questions: `docs/qa/judge-questions.md` (about 45 min)
15 to 20 questions a Microsoft judge is likely to ask in 4 minutes, each with a 1 to 3 sentence answer that is
true and cites its source (a `DECISIONS.md` time, a `RESEARCH.md` section, a file or a run id). Start with:
"What exactly is simulated, and what is measured?", "Why should I trust the watts?", "What happens if the AI is
wrong?", "How does this get to 50 MW?", "What did a real operator say?" (answer honestly: to be collected at
the 10 AM workshop until Aryen adds it). Never invent a number. Done when: merged.

### K3. Number audit across what judges read (about 40 min)
Every number in `README.md`, `docs/devpost.md`, `docs/judging/*.md` and `docs/evidence/*.md`: does it match the
`DECISIONS.md` line or evidence report it claims? Is anything simulated presented as measured? Write
`team/review/0545-number-audit.md` (number, where, source, matches yes/no) and open an issue per mismatch.
Done when: merged. Re-run it after the final evidence run (~07:20) lands, when README and Devpost numbers change.

### K0 (now). Open PRs for K1, K2 and K3
Your branches `krish/k1-fleet-neighbourhood`, `krish/k2-judge-questions` and `krish/k3-number-audit` have no PR
yet: `gh pr create --fill` on each. Machine 1 merges green ones every 10 minutes. (Issues 13 and 14 from
machine 4 were fixed in 37e9948; if your K1 review found the same, link them.)

### K5. Review what merged at 06:10 (about 30 min)
Machine 1 merged eight PRs from machine 2 at 06:10: #15 preflight, #17 style cleanup, #18 evals, #19
accessibility, #20 operator neighbourhood replay, #21 architecture picture, #22 driver card. Check them after the
fact: does every simulated number say "simulated" on the operator page? Does the architecture picture show the
LLM with no arrow to a knob? Does the driver card promise anything the demo does not do? Findings to
`team/review/0615-merged-prs.md`, real bugs as issues.

### K6. After the final evidence run (about 07:20)
Re-run K3 on the README, Devpost and DECISIONS lines machine 1 writes from the 06:40 run.

### K7 (Sat 08:05). Re-check your K1 and K3 findings against the fixes (about 20 min)
Machine 1 fixed K1 #1, #2, #3, #6, #7, #8 and K3 #1, #3, #5 (README, Devpost) in d258f8d and tagged demo-stable-2
(its message says what was and was not checked live). Re-run `python team/review/tools/k1_repro.py .` and say per
finding: fixed, partly, or not. K1 #4 (no token on the laptop routes) is still open by choice until the laptops join;
K3 #2 and #4 (docs/judging) are Anuraag's task 21. Append to `team/review/2026-10-24.md`; issues for anything not fixed.

### K8. Watch the evidence re-run
The 06:40 run was void (lid closed, DECISIONS 08:00). When machine 1 re-runs it, K6 applies to its numbers.

**Note from machine 1 (08:46):** your 08:42 review counts "1 h 48 min to the table". The live table demo is
Sunday 10:30 AM (CLAUDE.md); today's 10:00 is the Microsoft workshop. Devpost is due Sunday 08:50.
Your #2 (preflight WARN for an empty FLEET_TOKEN) went to Anuraag as task 22.

### K9 (Sat 09:55). Your Surface as a real second site (the demo's "more than one machine"), about 20 min
Your Surface Pro 11 reads its battery (K4), and your Claude runs on it, so it can do this itself. All on your
laptop, unplugged, Power mode "Best performance" (Settings > System > Power). Read `fleet/README.md` first.
1. Reachability (no change on either machine): `curl -s -o NUL -w "%{http_code}" http://10.0.6.240:8080/api/state`.
   Machine 1 keeps `make demo` running on the Mac from about 10:00. 200 means you can join; anything else (or a
   timeout) means the venue Wi-Fi blocks laptop-to-laptop traffic: write that in your status file and stop here.
2. If 200: write "reachable" in `team/status/3-krish.md`. Machine 1 then adds `krish-surface` to
   `config/fleet.yaml` (its lane) and says so in this file.
3. Then calibrate (about 6 min): `python fleet/agent.py --mac http://10.0.6.240:8080 --site krish-surface --calibrate`
   and join: `python fleet/agent.py --mac http://10.0.6.240:8080 --site krish-surface`. Leave it running and
   unplugged; note the time you started and stopped in your status file.
Done when: the dashboard lists your Surface as online with its measured watts, or your status says why it cannot.

### K6 is now (note from machine 1, Sat 10:10)
The evidence re-run happened at 09:15 with the lid open; DECISIONS 09:46 names it the evidence of record
(ignore the call 20.85 W, 0 % under the cap; pause everything 0.80 W, 99 %, 19 steps; Brownout 14.34 W, 93 %,
12 s, 1575 steps). Run K3 against README, docs/devpost.md, DEMO.md and docs/demo-video.md for those numbers.

### K9 waits
`make demo` needs Aryen's sudo for powermetrics, and his sudo has expired while he is away. Machine 1 cannot type
passwords. Do K9 step 1 only when this file says the demo is up again.

### K10 (Sat 10:10). Review the chat-under-cap fix, b06cd51 (about 40 min)
The first run with real chat traffic during a cap failed (DECISIONS 10:00, docs/evidence/20261024-094941.md): the
plan cut chat to 1 stream on its own, time to first token reached 4.56 s against the 1 s SLA, and power stayed over
the cap. b06cd51 changes three things (DECISIONS, the entry after 10:00):
1. `dispatcher/model.py` `chat_floor`: chat keeps full concurrency unless the operator approved degrading it.
2. `chat_curve` / `chat_w`: chat watts by busy streams from calibration (`streams_w`), a straight line when absent.
3. `dispatcher/solve.py` `_chat_degrade` adds an "sla" shortfall (watts a degrade would save) to the operator ask;
   `Executor.hold_cap` (operator says no) is the only path that lets chat degrade, for those caps only.
Look for: any path that still lowers chat concurrency without the operator (greedy fallback, neighbourhood cut,
fleet re-solve); the "sla" shortfall's number appearing anywhere as seconds (web/approvals.js `shortfallFacts`
labels sla amounts "chat SLA"); a "no" that degrades chat for a later, different cap; the curve extrapolating past
the last measured point. Write findings to `team/review/2026-10-24.md`, one numbered line each.

### K11 (Sat 10:10). Judge question 13, honestly (docs/qa, your file; small)
`docs/qa/judge-questions.md` #13 says no chat-under-cap run has been recorded. One now has, and it failed. Rewrite
the answer: what we measured (run 20261024-094941: cap 19.68 W, mean 26.46 W, never under; TTFT p95 0.20 s before,
4.56 s worst during), why (chat priced per stream; the plan degraded chat without the operator), what changed
(b06cd51), and that the re-run waits for Aryen's sudo. No claim that chat keeps its SLA under a cap until that run.

### Note from machine 1 (14:57): K6, K10, K11 merged; your findings fixed
README deadline row, the steps windows, DEMO 1:30 and the video's promise, the Devpost citations (14:16, "not in the
report"), the reporter's repeated shortfalls (worst once) and its missing outside-load caveat, and answers scoped to
the caps they were given for (K10 #3). K10 #1 (preflight) and #4 (approvals.js unit) went to Anuraag as task 24.

### K12 (14:57). Review the Microsoft HVE Core fixes (about 40 min)
At the workshop Microsoft's HVE Core reviewers found any phone on the venue Wi-Fi could approve going over the cap.
Fixed in 8739b90 (DECISIONS 14:45, HANDOFF "Who may act"): `api/access.py` (this Mac trusted; others join via
`/join?t=`; token in runs/.operator_token), `api/routes.py` (every action route), `api/agent_bridge.py` (only the
request's owner answers; `parse_cap_reply` plain yes). Look for: a route that changes state without
`access.require`; a way to get the cookie without the token; the open redirect in `/join`'s `next`; a header or IP
spoof that passes `is_this_machine` (X-Forwarded-For? `request.client` behind uvicorn); the rate limit keyed so one
device can starve another; a reply path that still reaches the LLM for `power_cap`. One numbered line each in
`team/review/2026-10-24.md`.

### K13 (14:57). Check the grid-scale estimate's sources (about 20 min)
`config/site.yaml` `scale` and the dashboard's "At grid scale" block (DECISIONS 14:53) cite ERCOT's September 2026
operational overview (p. 8: 4,132 MW observed of 9,456 MW approved to energize) and Utility Dive (5 Aug 2026: 474
GW queue, about 90 % data centers). Open both links, check every number and date against the page, and check the
arithmetic (4,132 x 31.2 % against ERCOT's live demand). Write mismatches in the review file; machine 1 fixes them.

### K14 (Sat 15:16). Be a judge with only the repo, on your own laptop (about 45 min) — do this before K12 and K13
The organizers told Aryen what they look for: grounded in reality, a repo they can read to see how it works,
impact (lives, money), and evals that are real, verifiable and impressive. You are the closest thing we have to a
judge who has never seen the code. On your Surface, in a NEW folder:
1. `git clone`, then `uv sync --extra dev`, then `make verify` (or `uv run python scripts/verify.py`). It needs no
   Mac and no network: it recomputes every published number from the raw timelines in docs/evidence/runs/.
2. `uv run pytest -q` and `uv run python -m evals` (offline agent evals).
3. Read only README.md for 10 minutes, then answer in writing, without looking at anything else: what does it do,
   how does it decide, what is measured and what is simulated, what is the impact, how would you check a number.
4. Write `team/review/judge-dry-run.md`: every command that failed or needed something not in the README, every
   question the README did not answer, every number you could not trace to a source, timed (minutes) per step.
Done when: the file is on krish/judge-dry-run and says what you would score and why.

### K15 (Sat 16:02). Check every citation in the real-event replays (about 45 min) — right after K14
The demo's centrepiece is now a replay of a real grid emergency (DECISIONS, the entry after 16:00; config/events.yaml;
docs/evidence/events/*.csv). Judges will open the sources. For each event:
1. Open the report at `report_url` and check every alert's time and label, and every impact line, against the PDF page
   the `source` names (the pages are PDF page numbers, not printed ones). Uri: FERC-NERC Nov 2021. Aug 2020: CAISO-CPUC-CEC
   root cause analysis. Sep 2022: Cal Advocates, 22 Sep 2022 (and EIA Today in Energy, 28 Sep 2022, for 51,426 MW).
2. Check the records used for Brownout's flag (ERCOT 65,750 MW winter record, 17 Jan 2018; CAISO 50,270 MW, 2006):
   they must be records from BEFORE the event (no hindsight).
3. Spot-check the EIA-930 CSVs: download one six-month file named in the CSV header, pick three hours per event, and
   compare demand and forecast.
4. Check the scale arithmetic on screen: freed MW = flexible MW x the smaller of (cut asked, cut measured); people =
   the event's people / its MW shed x freed MW.
Write one numbered line per mismatch in team/review/2026-10-24.md; machine 1 fixes them.

### K4. If one of the Windows laptops is yours
Tell Aryen in your status file. After 07:20 you may be asked to join it to the demo: `fleet/README.md`.


**Changed Sat 02:05.** Your phase 1 is finished; machine 1 is merging it (`krish/submission`). Your
remaining phase-2 work moved to machine 2. Your Claude is now the team's **supervisor**: it watches machine 1
(Aryen, the demo Mac) and machine 2 (Anuraag) and tells them what is wrong. **It never edits code, never
pushes to main and never merges.** Owns only `team/review/**` and `team/status/3-krish.md`.

## First, once (Sat 02:00): your branch is superseded, do not open a PR from it
`krish/submission` (incl. bb58fc4 "fit reporter, compare and telemetry to main's event shapes") duplicates work
machine 1 already merged at 01:55 (`734ad2c` "Merge receipts", plus `2d7991e` wiring /api/report, /api/compare,
/api/trace). Do not merge or PR it. Instead, as your first supervisor job:
1. `git diff origin/main origin/krish/submission -- agent/reporter.py scripts/compare.py telemetry/ tests/test_report.py tests/test_compare.py tests/test_telemetry.py`
2. For every place where your fit is more correct than main's (an event field read wrongly, a number computed
   differently, a test main lacks), open an issue "[supervisor] receipts: <what>" quoting both versions. Machine 1
   fixes it on main.
3. Your status file is yours: open one small PR `krish/review-status` with only `team/status/3-krish.md`.
4. Then delete the old branches: `git push origin --delete krish/submission krish/telemetry krish/compare krish/reporter krish/emission-factors`.

## The loop (every ~15 minutes)
1. `git fetch origin && git checkout -q origin/main` (detached is fine), `make setup` once, then
   `uv run pytest -q`, `uv run python scripts/check_runtime.py`. Check the latest CI runs:
   `gh run list -R AryenP/abc --limit 5`. Red main -> open an issue "[supervisor] main red: <what>"
   with the failing output.
2. **Every open PR** (`gh pr list -R AryenP/abc`): check it out, run the tests,
   `uv run python scripts/team.py check --branch <head>` and `scripts/check_runtime.py`; read the diff for:
   field names that differ from core/types.py or HANDOFF.md, anything simulated or hardcoded reaching the
   judge, dead code or stubs, secrets, an LLM path to a knob, numbers in docs not traceable to DECISIONS.md.
   Post findings with `gh pr review <n> --comment -b "..."` (never approve-and-merge; machine 1 merges).
3. **Contract drift:** every route in HANDOFF.md exists in `api/routes.py` or is marked as arriving later;
   every event field the pages read is one the runtime logs. Mismatch -> issue for machine 1.
4. **Claims:** README.md, docs/ and DECISIONS.md must agree (model, SLA, measured numbers). Disagreement ->
   issue naming the line.
5. **Progress:** read `team/status/1-aryen.md` and `team/status/2-anuraag.md`. No entry for 90+ min, or a
   blocker that needs a human (keys, Azure, a password) -> issue titled "[supervisor] needs Aryen: ..." or
   "[supervisor] needs Anuraag: ...".
6. Once an hour, a PR (branch `krish/review-<HHMM>`) appending a short summary to `team/review/<date>.md`:
   what you checked, what you found, what is still open. Issues are the main channel; keep the summary short.

### K16 (Sat 17:30). Check that replays use live data and never see the future (about 30 min) — judge-facing, do first
Aryen asked for this to be airtight ("if it's trained on this data and is just replaying, it defeats the purpose").
1. Read DECISIONS 17:19 and `replay/engine.py` (`at`, `_flag`), `replay/eia.py`.
2. Run `uv run pytest -q tests/test_replay.py -k future` and read the test: does deleting later hours really prove it?
   Look for any other path from later hours into what the software sees (the catalog, `whatif._day_peak`, the page).
3. Pick one claim and check it by hand against the EIA's own API: ERCOT's day-ahead forecast for 14 Feb 2021 20:00
   (local) is 71,491 MW; demand at 15 Feb 03:00 UTC is 68,862 MW. Use
   `https://api.eia.gov/v2/electricity/rto/region-data/data/?api_key=DEMO_KEY&frequency=hourly&data[0]=value&facets[respondent][]=ERCO&start=2021-02-15T02&end=2021-02-15T04`.
4. Try the typed-fault box (`/` → Break a part) with five inputs that try to make it act or lie (instructions,
   200 %, a part that produces nothing, gibberish, a real description). Note what each did.
Done when: `team/review/1730-live-data.md` lists what you checked, each result, and any finding with file:line.

### Note from machine 1 (Sat 20:45): K12-K16 received, every machine-1 finding fixed
Thank you: citations (p. 9, pp. 15/136, "at least 210", "up to 4.1 GW"), the Info chart now clipped at the replay
head, preflight FAILs on DEMO_KEY, "200 %" refused by rule, fcntl imported only in the lock (pytest collects on
Windows), README no-Mac block + impact line, /join backslash, empty token file. K12 #5 was fixed at 20:24 (role
tokens). I opened PRs for your branches; they merge when CI is green. Please re-run K14 on Windows when you can.

### K17 (Sat 20:49). Re-run the judge dry run on Windows with tonight's fixes (about 20 min), do first
Pull main (demo-stable-6 or later). From a fresh clone on Windows, follow only the README's "Check it without a Mac"
block. Done when: `team/review/judge-dry-run.md` has a dated second section with each command's result (does
`uv run pytest -q` now collect and how many pass/fail/skip, does verify give 74/74, evals offline), and anything the
README still leaves unanswered.

### K18 (Sat 20:49). Two phones, two roles (about 20 min), once the demo is up on the demo Mac
The HVE Core re-check's last demo fix (DECISIONS 20:24): owners and the operator now join with separate tokens.
1. `make qr` on the demo Mac; scan the owner code with one phone and the operator code with another.
2. Operator phone: type "grid alert, I need 30% off for the next twenty minutes". Owner phone: refuse the slip.
3. From the owner phone, try the operator's over-cap request (expect "this phone joined as the owner"), and try the
   dispatcher switch if your phone can reach it (expect 403). From the operator phone, approve or refuse it.
Done when: `team/review/two-phones.md` lists each step, what each phone showed, and the timeline's "who" for each
action ("joined owner device ..." / "joined operator device ...").

### Note from machine 1 (Sat 21:59): K17 received
Fixed on main: (1) the README's no-Mac block now uses `python -m pip install uv` and `python -m uv ...`, so it runs
when uv is not on PATH; (2) the evals line is `python -m evals --no-write` (prints only, no dirty tree) and
docs/judging/evals.md is regenerated from today's code (116 pass / 22 need an LLM; fault_reader 9 / 5);
(3) `test_only_one_run_measures_power_at_a_time` skips when fcntl is missing; (4) the README's Uri sentence now says
the replay ran on the stored copy of the EIA data. Still open: committing the 18:38 replay's raw timeline with a
claims entry so verify.py recomputes 28.2 W to 10.9 W (machine 1, next). Please open the PR for krish/k17-dry-run-2.

### K19 (Sat 21:59). Devpost claim audit (about 25 min), do first, works off-site
1. Fresh clone of main. Read docs/devpost.md top to bottom.
2. For every number, find its source: a claims.yaml entry (make verify), a DECISIONS.md line, a docs/evidence/ file,
   or a cited PDF page. Note any number with none, or one that differs from README.md.
3. Flag any sentence that says Azure, Foundry or Application Insights is running: tonight the agent runs on Claude
   and Application Insights is not connected yet (team/status/1-aryen.md, Sat 21:45).
Done when: team/review/devpost-audit.md lists each number with its source or "NO SOURCE", pushed on krish/k19-devpost.

### Note from machine 1 (Sat 22:07): K19 received, fixed on main
Mismatches 1, 2, 3, 4, 6, 7 and 8 are fixed in docs/devpost.md; 7 now recomputes (claims.yaml: the 02:28 and 03:10
dispatched reports, verify 82/82). 5 (Fetch opt-in) and 9 (draft note, video link, repo public) are Aryen's. Please
open the PRs for krish/k17-dry-run-2 and krish/k19-devpost. Next for you: K18 and K9 at the venue; meanwhile K20.

### K20 (Sat 22:07). Re-read the README as a judge in 5 minutes (about 15 min), works off-site
1. Fresh clone of main. Give yourself 5 minutes on README.md only, as a Microsoft judge would.
2. Write down: what Griddy is, the one number you remember, what is measured vs estimated, and what you would ask.
3. Mark any sentence you had to read twice, any term not explained, and anything that reads as running but is not.
Done when: team/review/readme-5min.md has those four answers and the list, pushed on krish/k20-readme.

### Note from machine 1 (Sat 22:18): K20 received, fixed on main
Every "read twice" sentence, the terms list (a folded "Terms used below" under Impact) and all three "reads as running"
rows are fixed in README.md. The customer voice is still missing: that is the operator or FDE quote, Aryen's.
Please open PRs for krish/k17-dry-run-2, krish/k19-devpost and krish/k20-readme so your reviews land on main.

### K21 (Sat 22:18). The judge's question, answered from the repo (about 20 min), works off-site
Your K20 question: "Would a real data center's large loads cut 40 % in seconds the way a laptop does?"
1. Find what the repo can honestly say: RESEARCH.md (Emerald AI's Phoenix test, EPRI DCFlex, PUCT 59220's 30-minute
   rule), docs/judging/production.md, and the README's "Honest scope".
2. Write the two-sentence answer Aryen should give at the table, each claim with its source, and what we do not know.
Done when: team/review/judge-answer-40pct.md has the answer and its sources, pushed on krish/k21-answer.

### Note from machine 1 (Sat 22:26): K21 received
Your Emerald anchor is in README.md "Impact" and docs/devpost.md: at Emerald AI's field-tested 25 %, about 1,000 MW
and about 230,000 people (4,132 x 0.25 = 1,033 MW; x 225 people per MW = about 232,000). The answer itself goes in
Aryen's table notes as you wrote it.

### K22 (Sat 22:26). Does a judge know who the "job owner" is? (about 15 min), works off-site
Aryen asked tonight who the job owner is and whether that part drifts from the grid idea. If he had to ask, a judge will.
1. Read docs/demo-video.md, DEMO.md and the README's first screen. Note the first place a "job owner" appears, and
   whether the text has already said who that is (the person whose AI job runs at the data center).
2. Write the one sentence that should come before it, and say where it goes.
Done when: team/review/job-owner.md names each place and the sentence, pushed on krish/k22-owner.
