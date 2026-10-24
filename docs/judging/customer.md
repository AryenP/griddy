# The customer: a data-center operator on a constrained grid

## Who
The operator of an AI data center that a utility can now order to cut load. They run a mix of work: interactive
inference that must stay up, training with deadlines, batch jobs that can wait. They answer to the utility on one
side and to the owners of those jobs on the other. Today's fallback when the grid runs short is backup diesel
(RESEARCH.md: during Winter Storm Fern, Jan 2026, the federal response for data centers was to order backup
diesel generators; DECISIONS 20:55).

## Their day with Brownout
1. **Morning: the plan for the next 24 hours.** The dashboard's dispatch map shows the live price curve and,
   under it, which job runs in which 15-minute slot. Training sits in the cheap afternoon hours, chat runs all
   day, batch takes a short slot. Each slot says why (price, cap, deadline). The operator changes the objective
   (cost, carbon, balanced) and the plan repaints.
2. **The call: a cap from the utility.** It arrives the way utilities already send it, as an OpenADR 3.1 event
   (`POST /openadr/event`), or the operator types it in their own words ("grid alert, I need 30% off for the
   next twenty minutes") on the operator page. Brownout reads it back in one sentence. If something is missing,
   it asks exactly one question. If the text tries to do something it may not (operate a knob, claim an
   approval), it is rejected.
3. **The trade-off is the owner's call, not Brownout's.** If the cap can be met by moving work, the solver
   just does it. If a deadline would slip, the job's owner gets a message on their phone and answers in their
   own words ("no, this has to finish by 9 AM Monday"). If the owner refuses, the operator decides whether to
   go over the cap. Until they say yes, the cap holds (DECISIONS 02:55).
4. **Compliance, measured.** The executor applies the plan at the slot boundary; measured watts drop under the
   cap. In the clean evidence run this took 7 s (DECISIONS 03:10). The operator page counts the time to
   compliance live.
5. **Receipts.** After the event the run report gives the baseline vs event watts, % reduction, time to
   compliance, approvals with names and times, and chat latency before and during. The comparison shows the
   same call with the dispatcher off. That record is what the utility asks for, and what a site can bring to a
   flexible-interconnection conversation ([compliance.md](compliance.md)).

## What they told us
> *To be collected at the Sat 10 AM Microsoft workshop.* Aryen adds the operator's or FDE's own words here and on
> the dashboard header (`config/site.yaml` `quote`); until then the dashboard shows no quote rather than a
> made-up one.

## What we do not know yet
- Real site job mixes and how much of their load is deferrable: **to be measured** with a design partner.
- Which approval channel operators already use (Teams is the assumption, [production.md](production.md)).
- How often caps arrive, how much notice they give, and how long they last at a given site: depends on the
  program; the rules give the outline (PUCT 59220: ≥60 min notice when practicable, 30-minute capability).
