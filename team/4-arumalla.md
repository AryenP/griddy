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

## Moved to machine 2 (Anuraag) at 5:40 AM
The picture (task 1) and the driver's cheat sheet (task 2) went back to Anuraag, so you can supervise.
If you already started either one, push what you have on a branch and say so in your status file.
