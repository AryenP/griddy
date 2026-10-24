"""The roster must give every tracked file exactly one owner (or mark it shared), so no two
machines can edit the same file."""
import fnmatch
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
R = yaml.safe_load((ROOT / "team" / "roster.yaml").read_text())
# kit material committed at M0 that nobody edits during the hackathon
FROZEN = (".court/*", "report/*", "RESEARCH.md", "TRACKS.md", "reports/.gitkeep", "runs/.gitkeep",
          "*/__init__.py")


def _owners(path):
    return [m["number"] for m in R["members"] if any(fnmatch.fnmatch(path, g) for g in m["owns"])]


def test_tracked_files_have_one_owner():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    problems = []
    for f in files:
        if f in R["shared_append_only"]:
            continue
        o = _owners(f)
        if len(o) > 1:
            problems.append(f"{f}: owned by {o}")
        if not o and not any(fnmatch.fnmatch(f, p) for p in FROZEN):
            problems.append(f"{f}: no owner")
    assert not problems, "\n".join(problems)


def test_assigned_future_paths_do_not_overlap():
    probes = ["web/index.html", "web/owner.html", "scripts/qr.py", "agent/reporter.py", "agent/llm.py",
              "agent/intake.py", "telemetry/__init__.py", "docs/devpost.md", "api/routes.py",
              "tests/fixtures/openadr/event.json", "config/isos.yaml", "config/jobs.yaml",
              "web/operator.html", "evals/cases.yaml", "agent/channels/slack.py",
              "team/status/1-aryen.md", "team/status/2-anuraag.md", "team/status/3-krish.md",
              "team/status/4-arumalla.md", ".claude/settings.json", ".github/workflows/ci.yml"]
    for p in probes:
        assert len(_owners(p)) == 1, (p, _owners(p))


def test_status_files_belong_to_their_writer():
    for f in (ROOT / "team" / "status").glob("*.md"):
        o = _owners(f"team/status/{f.name}")
        assert len(o) == 1 and f.name.startswith(f"{o[0]}-"), f.name


def test_every_member_has_an_assignment_file():
    for m in R["members"]:
        assert (ROOT / m["assignment"]).exists(), m["assignment"]
