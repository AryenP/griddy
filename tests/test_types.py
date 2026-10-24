from datetime import datetime, timezone

from core.timeline import Timeline
from core.types import Action, CapRequest, Plan


def test_cap_request_roundtrip():
    r = CapRequest(source="email", target_pct=30, start=datetime.now(timezone.utc),
                   duration_s=600, raw="cut 30% for ten minutes", constraints=["keep chat fast"])
    assert CapRequest.model_validate_json(r.model_dump_json()) == r


def test_plan_shape():
    p = Plan(request_id="req-x", actions=[Action(rung=1, name="defer_batch")],
             expected_w=70, feasible=True)
    assert p.actions[0].status == "proposed"


def test_timeline_writes_and_reads(tmp_path):
    tl = Timeline(run_id="t", root=tmp_path)
    tl.log("note", msg="hello")
    tl.log("sample", wall_w=100.0)
    tl.close()
    events = list(Timeline.read(tmp_path / "t" / "timeline.jsonl"))
    assert [e.kind for e in events] == ["note", "sample"]
    assert events[1].data["wall_w"] == 100.0
