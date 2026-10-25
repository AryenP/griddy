# Defense: Brownout-Orbit

## Thesis
Brownout-Orbit is modestly better than the base idea, not a cure for it. It fixes the base demo's weakest moment (a watt number falling while nothing visible happens) and gives the priorities a natural reason. It cures none of the three charges jurors named most often (secondhand customer, asserted production path, self-authored baseline), and it adds build risk. It wins the Grand Prize only with the same verdict conditions plus a hard scope cut.

## Argument
1. Usefulness gets a visible unit. The base output is a chat reply and a meter. The variant's output is a flood map that keeps rendering while the meter drops. The headline becomes "time-to-first-map: X s uncapped, Y s under a 30% cap, routine work deferred." That is a service number tied to an outcome, which helps criterion 2. (Speculation: it only helps if the map looks plausible.)

2. The LLM job gets richer (charge 5, partly). The owner's free-form reply is naturally about deadlines and consequences: "The fine-tune can slip a day, but I need Sunday's tiles for Tuesday's report." The agent must reason over that and rewrite the plan. A well-written base negotiation could match this, but here it comes for free.

3. Permissions are self-evident. "The urgent flood job is never throttled" needs no explanation, so the default `permissions.yaml` is easy to defend in one sentence. It does not replace the Saturday FDE quote; it makes that quote easier to place.

4. Possibly closer to FDE customers. Mixed urgent and batch workloads under a budget may resemble what Microsoft FDEs deploy into more than "a data center under a utility order." Speculation, and the base customer is arguably more universal.

5. A cheap second prize. SpaceXSI ($400 plus keyboard) requires building in Cursor. This is a side benefit and should not drive the choice.

## Versus the base idea
| Charge | Cured? |
|---|---|
| 1. Customer secondhand | No. An EO team is a niche the builder has not spoken to. Arguably worse. |
| 2. Production path asserted | No change. |
| 3. Self-authored baseline | No change. The 5-minute baseline and time-to-compliance still apply. |
| 4. Lamp may show nothing | No change. |
| 5. LLM looks optional | Partly. |

Net: one charge partly cured, one risk added (two hard things solo in 36 hours). The variant is better only if the following discipline holds:
- Use a small pretrained or lightly fine-tuned U-Net and precompute tile subsets before the venue. Do not train on site. (Speculation: Sen1Floods11's hand-labelled subset should be small enough to stage early. Check its size now.)
- Keep the chat endpoint as the SLA workload fallback so the base demo stays intact.
- Hold a go/no-go at Saturday 6 PM: no believable map by then, revert to the base idea.

On those terms the ceiling is higher and the floor is the base idea. If the segmentation slips, the builder has spent hours not spent on the Saturday rehearsals the verdict says matter most.
