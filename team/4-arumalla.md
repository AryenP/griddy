# 4 Arumalla: briefing pages for the judges

Hi! Your earlier job (the AI helper code) moved to machine 1 at 1:45 AM. You have a new job now (Sat 4:55 AM).
It is all yours: you work in your own folder, `docs/briefing/`, and nobody else touches it. So you cannot
break anyone's work, and nobody can break yours.

## How to start
1. In the repo folder, get the latest copy: `git pull`
2. Check who you are: `uv run python scripts/team.py whoami --save`. It should say you are number 4.
3. For each task, make a new branch (your own working copy): `git checkout -b arumalla/<short-name>`,
   for example `arumalla/picture`.
4. Only add or change files in `docs/briefing/` and your notes file `team/status/4-arumalla.md`.
   A safety check stops changes anywhere else.
5. When a task is done: commit, push the branch, and open a pull request (a request to add your work to
   the main copy): `gh pr create --fill`. Machine 1 checks it and adds it.
6. After each task, add a few lines to `team/status/4-arumalla.md`: what you finished, what is next, and
   anything that is stopping you.

## Ground rules (from CLAUDE.md)
- Never make up a number. Every number must come from `DECISIONS.md` or `RESEARCH.md`. If it is not
  there, write "to be measured".
- No passwords or keys in any file, ever.
- Short, plain commit messages.

## DO THIS FIRST (Sat 5:05 AM): the laptop power test, about 2 minutes
Aryen wants to use the team's laptops as extra "sites" in the demo. First we must know if your laptop can
measure its own power. This test answers that. It changes nothing on your laptop.
1. **Unplug the charger.** The battery only reports its power while the laptop runs on battery.
2. Get the latest copy: `git pull`
3. Open PowerShell in the repo folder and run:
   `powershell -ExecutionPolicy Bypass -File fleet\battery_probe.ps1`
   It reads the battery for 20 seconds with the laptop resting, then 20 seconds with the laptop working hard.
   The fan may spin up. That is expected.
4. It ends with a few lines starting at `== SUMMARY`. The last line says GOOD, SLOW, NO READING, PLUGGED IN or
   UNCLEAR. If it says PLUGGED IN, unplug and run it again.
5. Copy the SUMMARY lines into `team/status/4-arumalla.md`, on a branch called `arumalla/probe`, and open a
   pull request: `gh pr create --fill`. Also send the summary to Aryen.
6. This script is new and could not be tested on the Mac. If it shows an error, copy the whole error into your
   status file the same way. That helps just as much.
7. **Your Claude cannot do this test.** It runs in the cloud, not on your laptop. You (the person) run it
   on the Windows laptop and paste the summary to your Claude or to Aryen. The full laptop guide, including
   how a laptop joins the demo later, is `fleet/README.md`.
Then go on with task 1 below.

## Your tasks, in order

### 1. The picture: `docs/briefing/architecture.svg`
**What:** one picture that shows how Brownout works, for Devpost and the README.
Boxes and arrows, left to right:
- Grid data (CAISO and ERCOT electricity prices) → the planner (the "solver") → the 24-hour plan →
  the controller → the three jobs on the Mac (chat, training, batch).
- The power meter (macOS "powermetrics") → the record of everything that happened (the "timeline") →
  the dashboard and the receipts.
- People: the job owner and the operator say yes or no to risky changes.
- The AI helper (the "agent") sits beside the planner. It reads requests, explains the plan, and asks
  people questions. Draw its arrows only to "requests", "explanations" and "questions".
  **It must have NO arrow to the controller or the jobs: the AI never turns a knob.** This is the most
  important part of the picture.

Under each box, write the code file in small text (for example `dispatcher/solve.py`). `README.md` and
`SPEC.md` tell you which file does what.
Use any drawing tool you like (Excalidraw or draw.io are easy) and export as SVG with a white or light
background. The text must be easy to read when the picture is 700 pixels wide.
**Done when:** the SVG is in `docs/briefing/`, it opens in a browser, and your pull request is merged.

### 2. The driver's cheat sheet: `docs/briefing/driver-card.md`
**What:** one page for whoever runs the 4-minute demo, so they do not have to remember anything.
Put in it, in this order:
- **Before you start:** the commands `make preflight`, then `make demo`, and the web addresses of the
  dashboard, chat, owner, operator and proof pages (you find them in `DEMO.md`).
- **The 4-minute script** from `DEMO.md`: each step with its time (0:00, 0:15, ...), what to click or type,
  and the one sentence to say.
- **Dashboard shortcuts:** D turns the dispatcher on or off; 1, 2, 3 pick cost, carbon or balanced;
  R jumps to the receipts.
- **If something breaks, what to say (truthfully):** internet down, chat model stopped, AI helper offline.
  Use the "Failure drills" part of `docs/rehearsal.md` and turn each one into one sentence to say out loud.

**Done when:** it fits on one printed page and your pull request is merged.

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

## When all four are done
Write "all four done" in `team/status/4-arumalla.md`. Machine 1 will add more tasks here.
