# K21: "Would a real data center's large loads cut 40 % in seconds the way a laptop does?"

Machine 3 (Krish), Sat 22:30 PT, main at `024f91f`. Answered only from what the repo cites: RESEARCH.md (**R**),
docs/judging/production.md, README.md "Honest scope", DECISIONS.md (**D**).

## The answer to give at the table (two sentences)
"No one has shown 40 % in seconds at data-center scale: the closest field result is Emerald AI cutting a real GPU
cluster in Phoenix by 25 % and holding it for three hours with SRP, EPRI puts the potential at 10 to 30 %, and Texas
now requires co-located data centers to be able to curtail fully within 30 minutes, so seconds is this laptop's
number and 40 % is the alert's ask, not a measured site. What we built and measured is the loop that decides which
work can wait, asks its owner, acts and proves it, and the Uri figure credits only the share the grid asked, labelled
as an estimate; at Emerald's 25 % the same arithmetic gives about 1,000 MW and about 230,000 people."

## Sources for each claim
| Claim | Source |
|---|---|
| Emerald AI: 25 % GPU-cluster reduction held 3 h, Phoenix, with Oracle Cloud, NVIDIA, EPRI, SRP (results 1 Jul 2025) | R "Prior art"; docs/judging/production.md:31 |
| EPRI DCFlex: 10 to 30 % peak-reduction potential (Reuters, 8 Oct 2026) | R "Why a utility can order this" |
| PUCT Docket 59220 (24 Jul 2026): full curtailment on ERCOT instruction, 30-minute capability, >= 60 min notice "when practicable" | R "Why a utility can order this" |
| "In seconds" is this Mac: 5 s, 7 s, 12 s to compliance | D 02:28, D 03:10, D 09:46 (recomputed by verify.py) |
| 40 % is the cut ERCOT's EEA 3 alert asks of our sites in the replay; the Mac measured 61 % and is credited 40 % | config/events.yaml (`cut_pct: 40`); D 18:38 |
| One machine, 0.5 to 26 W, SoC power, not a wall meter; at 50 MW the knobs are cluster schedulers and power caps | README "Honest scope"; D 02:28, D 03:10 |
| Real programs judge compliance on 5 to 15 min revenue-grade interval meters against a baseline | R "Prior art" (how compliance is verified) |

## The Uri estimate at the shares the sources support (arithmetic, labelled estimate)
Same inputs as the README (ERCOT large loads up to 4,132 MW, the sum of each load's own September peak, ERCOT
overview PDF p. 9; Uri: 20,000 MW shed, 4.5 million people out, so 225 people per MW shed, FERC-NERC PDF pp. 10, 15):

| Share cut | MW freed (up to) | Share of Uri's shed | People at Uri's ratio |
|---|---|---|---|
| 10 % (EPRI low) | 413 | 2.1 % | about 93,000 |
| 25 % (Emerald, measured at a real cluster) | 1,033 | 5.2 % | about 232,000 |
| 30 % (EPRI high) | 1,240 | 6.2 % | about 279,000 |
| 40 % (the alert's ask; README's figure) | 1,653 | 8.3 % | about 372,000 |

Suggestion for README.md "Impact" and docs/devpost.md: keep 40 % (it is what the replay credits), and add "at
Emerald AI's measured 25 %, about 1,000 MW and 230,000 people", so the headline has a field-tested anchor.

## What we do not know (say so if asked)
- How fast a real GPU cluster sheds: the repo has no measurement of how long checkpoint-and-preempt takes at megawatt
  scale (Emerald's result is a 25 % cut held for three hours, not a ramp time).
- What share of ERCOT's 4.1 GW of large loads is flexible AI compute: the repo cites the total, not its make-up.
- Whether inference SLAs hold at site scale under a 40 % cut: measured only on this Mac (D 14:16).
- How a utility's 5 to 15 min interval meter would score a seconds-scale response: our meter is 1 Hz on the SoC.
