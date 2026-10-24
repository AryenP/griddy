# Driver card (print one page; keep it beside the Mac)

The script is DEMO.md. This card is what to type, click and say. Every number the judge sees comes from the
screen; never say a number that is not on it.

## Before walking to the table (demo Mac, same terminal throughout)
1. `git describe --tags`: the demo runs from the newest `demo-stable-N` tag, never from whatever main is.
2. `make preflight`: every line PASS, or a WARN you understand. A FAIL prints its fix on the same line.
   If sudo FAILs: `sudo -v` in this terminal (or install the pinned powermetrics rule, team/README.md).
3. `make demo`: the dashboard is up in under 2 minutes. Open `http://localhost:8080/` full-screen.
4. `make qr`: QR codes for the chat, owner and operator pages (PNGs in `reports/qr/`). Put the chat QR on the
   table, open the owner page on the judge's phone and the operator page on yours.
5. A browser tab on Application Insights, Transaction search, last 30 minutes. `/api/trace` is the fallback.

| Page | URL (host and port from `PUBLIC_URL` in `.env`) |
|---|---|
| Dashboard | `/` |
| Chat | `/chat` |
| Job owner | `/owner.html` |
| Grid operator | `/operator.html` |
| Proof (three recorded runs) | `/proof.html`, or the link under Receipts |

## Hotkeys
| Page | Key | Does |
|---|---|---|
| Dashboard | `D` | dispatcher on / off (the kill switch) |
| Dashboard | `1` `2` `3` | objective: cost, carbon, balanced |
| Dashboard | `R` | scroll to the receipts |
| Operator | `E` | focus the request box |
| Operator | `A` | focus the "ask why" box |
| Operator | `N` | start / stop the neighbourhood replay (simulated) |

## The four minutes
| Time | Do | Say |
|---|---|---|
| 0:00 | Point at the header. | "When the grid runs short, the plan for AI data centers is diesel generators. This is the alternative." Then the operator quote if it is on screen; if not, skip it, never paraphrase one. |
| 0:15 | Judge picks **Grid** (the select) and an objective (`1` `2` `3`). | "Live prices from the ISO with their interval time; the solver repaints all 24 hours." Read the two-sentence explanation off the screen. |
| 0:45 | Judge scans the chat QR and asks anything. | "The chat stays up. The tile shows time to first token against its SLA, measured on this Mac." |
| 1:15 | Operator page, `E`, judge types or dictates "grid alert, I need 30% off for the next twenty minutes". **Send request**. | "It reads the request back with real watts before anything moves." |
| 1:45 | Owner page on the judge's phone: they refuse in words ("no, this has to finish by 9 AM Monday"). | "A refusal makes the deadline hard. The cap is held while the operator decides." Point at the time-to-compliance counter on the operator page. |
| 2:30 | Switch objective or ISO on the dashboard. | "Same jobs, new live curve: the plan and the Mac follow." |
| 3:00 | Operator page: "cut 90% for 20 minutes". | "It says what it can't do: the floor with chat protected, in watts, from the solver." |
| 3:30 | `R` on the dashboard, then **Show these runs** on the proof page. | "Recorded runs, not live: the same call ignored, everything paused, and Brownout. Measured by powermetrics." Then one decision in Application Insights. |
| 3:50 | Close. | "This is a laptop's watts. The feeds, the solver, the approvals and the audit trail are the same at 50 megawatts, and the request came in the format utilities already send." |

Optional, only if there is time and the judge asks about the wider grid: operator page, **Replay the evening peak
(simulated)** (`N`). Say first: "This box is simulated: the homes follow today's real forecast shape, our own
watts stay measured, and the utility's cut it sends is a real cap to the real dispatcher."

## When something breaks: say it, don't hide it
| What you see | Say | Then |
|---|---|---|
| Feed age badge says stale; plan "on last known data" | "The ISO feed is stale; the plan runs on the last data it had, and the screen says so." | Carry on. It recovers when the network does. |
| Chat page shows an error | "The chat model on this Mac stopped; the dispatcher and the meter keep running." | `ollama serve` in another terminal if there is time. |
| Badge says "agent offline" | "No model right now. Plain forms like '30% for 20 minutes' still work without it, and nothing pretends to be the agent." | Use plain forms only. |
| No power reading | "The meter has stopped, so there is no measured number to show, and the page says so." | Check the terminal running `make demo`; restart it from the same terminal. |
| The judge types something odd | Let the agent ask its one clarifying question. | Answer it, or rephrase as a plain form. |
| Application Insights shows nothing yet | "Azure can take a few minutes to ingest; here are the same spans from the app." | Open `/api/trace?n=50`. |
