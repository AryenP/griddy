# 4 Arumalla: supervisor (since Sat 5:40 AM)

Aryen made you the supervisor. Your job: watch the work of machine 1 (Aryen's Mac) and machine 2 (Anuraag),
and tell them quickly when something is wrong. You do not change their code. You only report.
You also keep two small writing tasks (the workshop questions and the source check, at the bottom).

## Every 10 minutes
1. Get the latest copy: `git pull`
2. Run the tests: `uv run pytest -q`. The last line should say "passed" and nothing "failed".
3. Look at what changed since last time: `git log --oneline -15`. For each new change from machine 1 or
   machine 2, open it (`git show <the code at the start of the line>`) and check these five things:
   - **No made-up numbers.** Every number a judge sees must come from a measurement, from the live grid
     feed, or from `DECISIONS.md` / `RESEARCH.md`. If you cannot tell where a number comes from, report it.
   - **Simulated things say "simulated".** Some of the demo is now simulated on purpose (the neighbourhood
     power line: homes, solar, 20 data centers, a diesel generator). Aryen decided this at 5:35 AM. Every
     simulated thing must be labelled "simulated" on screen and in the files. Measured things must not be
     labelled simulated. Report any mix-up. This is the most important check tonight.
   - **No secrets.** No passwords, keys or connection strings in any file.
   - **The checks on GitHub are green.** `gh run list -L 3` should show "success".
   - **It does what its message says.** Read the commit message, then the change. Do they match?
4. If something is wrong, open a GitHub issue that machine 1 or 2 will see:
   `gh issue create --title "[supervisor] <one line: what is wrong>" --body "<where (file and line), what you
   expected, what you saw>"`. Keep it short and exact.
5. Write one line in `team/status/4-arumalla.md`: the time, "checked", and any issue you opened.
   Send it on a branch `arumalla/status-<time>` with a pull request, like before.

## Your two writing tasks
Do these between checks. Task 3 is due first (9:30 AM).

### 3. The question sheet for the Microsoft workshop: `docs/briefing/workshop.md`
At 10 AM Saturday there is a Microsoft workshop. Aryen will talk to Microsoft people there. We need one
real quote from them for the dashboard.
Write:
- 6 to 8 short questions (one line each) for a Microsoft engineer or a data-center person, about: how data
  centers handle grid emergencies today, who decides which jobs slow down, what proof the power company
  wants afterwards, and whether a tool like Brownout would help them.
- A box to fill in during the talk: the person's name, their job title, the exact words they said, and
  "OK to show this on our screen? yes / no".

**Done when:** your pull request is merged before 9:30 AM.

### 4. Check our sources: `docs/briefing/sources.md`
`RESEARCH.md` lists facts and the web links they came from. Judges may click them.
For each link in `RESEARCH.md`:
- Open it. Does it load?
- Does the page really say what `RESEARCH.md` says? Check the number or the date.

Make a table with these columns: the fact (short), the link, "loads? yes / no",
"says it? yes / no / partly", and a note.
**Do not change `RESEARCH.md`.** If something is wrong, just mark it in your table; machine 1 fixes it.
**Done when:** every link has a row and your pull request is merged.

## Note from machine 1 (Sat 10:21)
- **Skip task 3.** The workshop was at 10 AM. Machine 1 gave Aryen the questions in chat. You do not need to
  write `docs/briefing/workshop.md`.
- **Do task 4 next** (the source check). Then task 5 below.

### 5. Brownout in plain words: `docs/briefing/plain-words.md`
Some judges are not engineers. Any of us at the table may get a simple question. This page gives simple answers.
1. Write 8 short questions a non-engineer might ask. Examples: "What does it do?", "Is the power data real?",
   "What part is pretend?", "What happens to someone using the chat when power is cut?", "Who says yes or no?"
2. Answer each one in 2 or 3 short sentences. Use everyday words. No numbers you cannot point to.
3. Under each answer, write where it comes from: a file and a line, like `README.md:11` or `DECISIONS.md` and
   the time of the entry (for example "DECISIONS 09:46").
4. Be honest about the chat question. Our first test of chat during a power cut failed. The details are in
   `DECISIONS.md`, the entry at 10:00 and the one after it. The fix is in, but it is not tested yet. Say that.
5. The "pretend" part: the neighbourhood power line on the dashboard is SIMULATED. Say so in your answer.
   Everything about the Mac itself (watts, prices) is measured or live.
**Done when:** the page has 8 questions, each answer has its source, and your pull request is merged.

## Moved to machine 2 (Anuraag) at 5:40 AM
The picture (task 1) and the driver's cheat sheet (task 2) went back to Anuraag, so you can supervise.
If you already started either one, push what you have on a branch and say so in your status file.

## Note from machine 1 (Sat 17:30)
The main page changed. It now shows the grid in 3D. Judges can also "break" a part of the grid.

### 6. Try the main page like a judge, then write what confused you: `docs/briefing/try-it.md`
1. Open http://localhost:8080 on the demo Mac (ask Aryen or machine 1 if it is not running).
2. Click "Winter Storm Uri, Texas". Then click "Replay it live". Watch for two minutes.
3. Click "Break a part". Pick the gas plant. Click "Trip it".
4. Click "Break a part" again. In the box, type how something breaks, in your own words. Click "Read it".
   (A "what-if" is a pretend break. Its size comes from the real grid numbers right now.)
5. Write 5 to 10 short lines in `docs/briefing/try-it.md`. One line for each thing that confused you,
   or a word you did not understand. Write what you expected to happen.
Done when: the file has at least 5 lines, in your own words, and you pushed it.

## Note from machine 1 (Sat 21:36)
Do task 6 first. Then task 7. Both are short. Both help the judges.

### 7. Check that every number says where it comes from: `docs/briefing/sources-check.md`
A judge will ask "where does this number come from?". Each number on the screen should answer that by itself.
A "source" is the place a number comes from. For example: "measured by macOS powermetrics" or "EIA, hour ending 20:00".
1. Open http://localhost:8080/info.html on the demo Mac. This is the Info page.
2. Look at the four big numbers at the top. Under each one there is a small grey line. That line is its source.
3. Click a city on the main page (http://localhost:8080). Click "Open the Houston map". Look at the small line at the bottom.
4. Open http://localhost:8080/proof.html. This is the Proof page. Look at each number there too.
5. In `docs/briefing/sources-check.md`, write one line per number. Write the number, the page, and its source.
   If a number has no source line, or you cannot understand the source, write "NO SOURCE" or "UNCLEAR" on that line.
6. Push it. Then write one line in `team/status/4-arumalla.md` that says you finished.
Done when: the file has at least 8 lines, each one names a page, and you pushed it.
