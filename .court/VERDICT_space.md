# VERDICT — Brownout-Orbit (space variant) vs base, 23 Oct 2026 8:30 PM

Question: is the Earth-observation variant more likely to win the Microsoft Grand Prize than the base idea? Quick mode, 6 jurors, rebuttals skipped for time (defense had already conceded "modestly better, not a cure, adds risk").

**BASE, 6–0.**

| Juror | Vote | Reason |
|---|---|---|
| Microsoft FDE | BASE | Cures none of the base's weak points, loses the curtailment evidence, adds a second hard build. |
| Data-center ops | BASE | Utility-order thesis with lamp, refusal and 90% moment is the memorable story; EO team has no curtailment order. |
| Hackathon veteran | BASE | Two hard builds solo; end-to-end more likely to break at the table. |
| EO flood-mapping scientist | BASE | A believable SAR flood map takes real work; risk of a weak or pre-rendered map undercutting credibility. |
| Utility DR manager | BASE | Same weak points unfixed; customer moves to a niche with no regulation behind it. |
| Sceptical student | BASE | Less jealous of a riskier build with a weaker customer. |

## The one thing all six said would flip them
Keep the framing "data center under a utility order" and make the EO job a **tenant workload**, **only if** a pretrained flood-segmentation checkpoint and a small staged Sen1Floods11 tile subset run live on the box with no added risk to the power stack and the chat endpoint kept as the fallback.

## Ruling
- Framing stays base. Customer stays "AI facility under curtailment obligation".
- Tenant workloads become EO jobs **if and only if** a go/no-go test passes by Sat 1 PM: pretrained model found (e.g., a public Sen1Floods11 U-Net / Prithvi-flood checkpoint), a 20–50 tile subset staged locally, inference renders a map on the box in under 2 hours of work. Otherwise the tenants stay generic (training loop + embedding batch) and nothing is lost.
- If the EO tenants ship: the "urgent" tile job becomes a second protected workload with a deadline, the historical reprocessing is the droppable batch, and the fine-tune is the deferrable job. The flood map appears on the dashboard while the meter drops. Opt into Best Planet-First.
- SpaceXSI track ($400 + keyboard) requires the project be built with Cursor. Not worth a tooling switch for the Grand Prize target; opt in only if Cursor ends up being used anyway.
- The base verdict's six conditions for acquittal still apply and matter more than this choice.
