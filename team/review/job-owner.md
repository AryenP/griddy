# K22: does a judge know who the "job owner" is?

Machine 3 (Krish), Sat 22:40 PT, main at `411f36c`. Read the README's first screen, DEMO.md and docs/demo-video.md.
In all three, "owner" appears before anything says who that is. The sentence that fixes it, in plain words:

> **"Think of this laptop as a small data center: teams run AI work on it (a model training run, a nightly batch,
> a chat service), and each job has an owner, the person on that team who set its deadline."**

## Where "owner" first appears, and where the sentence goes
1. **docs/demo-video.md:12 (0:00), most urgent.** The video opens on "Owner's phone ... Owner types 'No, this has to
   finish by 9 AM Monday'" with the voice "The grid just asked this machine for 30 % less power. The training job's
   owner said no." A viewer has not been told there is a data center, a team or a job. Put a shortened version first
   in the 0:00 voice: "This laptop is standing in for a data center. A team's AI model is training on it, due Monday
   9 AM. The grid just asked for 30 % less power, and the team's owner of that job said no."
2. **README.md:9.** "...executes the current slot on real hardware, asks job owners before breaking their deadlines".
   Nothing above says whose jobs. Put the sentence right after the tagline (line 5), before "Griddy is a grid-aware
   compute dispatcher", or fold it into line 7: "...schedules every AI job (each belongs to a team, whose owner set
   its deadline) over the next 24 hours...".
3. **DEMO.md:5 ("operator and owner pages via QR") and 1:30 ("They are the owner. Their phone shows the training
   owner's request").** The script casts the judge as the owner without saying who that is. At 1:30 say: "Now you are
   the team whose model is training on this machine (ml-team in config/jobs.yaml): it has to be done by Monday 9 AM."

## A second word that drifts: "operator" means two different people
- DEMO.md 1:10 "They are the utility. On the operator page"; api/access.py: "The OPERATOR token makes it the utility's
  device". Here the operator is the **grid's** side (the utility asking for the cut).
- README.md "Who controls what": "The operator decides when the cap and a refused deadline conflict. Until they
  approve going over the cap, the running plan holds it." Here the operator is the **data center's** person who
  answers the over-cap request (policy.yaml `operator: ops`).
A judge who hears "the operator approved going over the cap" can read it as the utility approving its own cap being
broken. Pick one: call the grid side "the utility" everywhere (page title "Utility", the QR label "utility"), and keep
"operator" for the data center's person; or the reverse, but never both. The three people in the story are then:
**the utility** (asks for the cut), **the data center's operator** (decides whether to go over it), **the job owner**
(the team whose job would slip).

**In code it is one role, not just one word.** api/access.py's docstring: the OPERATOR token "makes it the utility's
device (requests, caps, replays, what-ifs, the dispatcher, the over-cap approval)". So the phone that sends the
utility's cut is also the phone that approves going over it, while config/policy.yaml names the over-cap approver as
the data center's `operator: ops`. For the demo (one judge, one operator phone) this works, but the story a judge
hears is "the utility asked for 30 % and then approved not getting it". Either give the over-cap approval to a third
role (the data center operator, on this Mac or its own QR), or say plainly at 1:30 that the operator phone plays the
data center's operator, not the utility, once the cut has been sent.
