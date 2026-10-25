"""The proof page (team/2-anuraag.md task 10): its scripts, the routes it reads, and the label that says the
numbers are recorded, not live."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
HTML = (WEB / "proof.html").read_text(encoding="utf-8")
JS = (WEB / "proof.js").read_text(encoding="utf-8")


def test_loads_only_its_own_scripts():
    assert re.findall(r'<script src="([^"]+)"', HTML) == ["common.js", "proof.js"]


def test_reads_only_the_recorded_run_routes():
    routes = {re.sub(r"\$\{[^}]*\}", "{}", r) for r in re.findall(r"[`\"'](/api/[^`\"'?]*)", JS)}
    assert routes == {"/api/runs", "/api/runs/{}/series", "/api/compare"}, routes
    assert "postJSON" not in JS and "connectWS" not in JS     # recorded runs only: no commands, no live socket


def test_says_recorded_not_live():
    assert "recorded, not live" in HTML
    assert JS.count("recorded, not live") >= 2                # under the traces and under every comparison


def test_draws_the_three_policies_from_the_contract():
    for policy in ("baseline", "pause_all", "dispatcher"):
        assert f'id: "{policy}"' in JS and f'id="pick-{policy}"' in HTML


def test_the_evidence_runs_of_record_are_picked_by_default():
    """Sat 17:38: the newest run on the demo Mac is often a test session; Proof defaults to the comparisons of record
    in docs/evidence/claims.yaml (GET /api/runs marks them `of_record`) and says so."""
    import yaml
    claims = yaml.safe_load(open("docs/evidence/claims.yaml"))["comparisons"]
    record = [c for c in claims if "of record" in c["name"]]
    assert len({c["dispatched"] for c in record}) == 1 and {c["baseline"].split("-")[-1] for c in record} == {"baseline", "pause_all"}
    assert "x.of_record" in JS and "evidence runs of record" in JS
