"""`make verify` in CI: every number in docs/evidence/claims.yaml recomputes from the committed raw timelines, and
every page that quotes it still says it. The timelines are real measured runs (docs/evidence/runs/), not fixtures."""
import yaml

from scripts import verify


def test_every_published_number_recomputes_from_the_raw_timelines():
    claims = yaml.safe_load(verify.CLAIMS.read_text(encoding="utf-8"))
    rows = verify.check(claims)
    bad = [r for r in rows if not r[4]]
    assert not bad, "\n".join(f"{n}: {m} claimed {w!r}, recomputed {g!r}" for n, m, w, g, _ in bad)
    assert len(rows) >= 70


def test_precision_rule():
    assert verify.matches(14.34, 14.337) and not verify.matches(14.34, 14.326)
    assert verify.matches(93, 93.21) and not verify.matches(80, 83.59)
    assert verify.matches(None, None) and not verify.matches(None, 0.0) and not verify.matches(12, None)
