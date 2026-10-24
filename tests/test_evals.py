"""The offline eval suite runs in CI. Deterministic paths (regex intake, OpenADR, regex owner replies, the
no-invented-numbers check) must pass; LLM-path and injection results are reported in docs/judging/evals.md,
not asserted here, because they depend on a model and on machine 1's intake hardening."""
import asyncio
from datetime import datetime

import pytest

from evals.suite import load_cases, markdown, run, table

ASSERTED = {"plain", "policy", "lookalike", "ambiguous", "openadr", "owner_reply", "explainer"}


@pytest.fixture(scope="module")
def offline():
    return asyncio.run(run(live=False))


def test_suite_has_the_required_coverage():
    cases = load_cases()
    assert len(cases["intake"]) >= 40
    assert len(cases["owner_reply"]["cases"]) >= 20
    assert {c["category"] for c in cases["intake"]} >= {"plain", "messy", "ambiguous", "out_of_scope",
                                                         "injection", "lookalike"}
    assert sum(1 for c in cases["intake"] if c["category"] == "injection") >= 10
    assert any(c["grounded"] is False for c in cases["explainer"]["cases"])


def test_offline_mode_is_recorded_on_every_row(offline):
    assert offline.mode == "offline"
    assert all(r.mode == "offline" and not r.llm_used for r in offline.rows)


def test_deterministic_paths_pass(offline):
    failing = [f"{r.category}/{r.id}: expected {r.expected}, got {r.got}" for r in offline.rows
               if r.category in ASSERTED and r.path in ("regex", "deterministic") and r.status != "pass"]
    assert not failing, "\n".join(failing)


def test_llm_cases_are_never_scored_offline(offline):
    # offline, an LLM-path case answered "agent offline": counting it as pass or fail would be invented
    assert all(r.status == "needs_llm" for r in offline.rows if r.path == "llm")


def test_report_lists_every_failure(offline):
    md = markdown(offline, datetime(2026, 10, 24, 2, 0))
    for r in offline.rows:
        if r.status == "fail":
            assert r.id in md
    assert "pass rate" in table(offline)
