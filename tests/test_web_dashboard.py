"""Dashboard-specific static checks (the per-page checks for every page are in test_web_pages.py)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "app.js").read_text(encoding="utf-8")


def test_dashboard_loads_chart_js_and_its_scripts():
    assert re.findall(r'<script src="([^"]+)"', HTML) == [
        "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js", "common.js", "app.js", "receipts.js"]


def test_posts_only_to_contract_routes():
    routes = set(re.findall(r'post\("(/api/[\w/]+)"', JS))
    assert routes <= {"/api/iso", "/api/policy", "/api/dispatcher"}, routes


def test_chat_sla_is_time_to_first_token():
    # policy.sla.chat_p95_s no longer exists (HANDOFF.md, Sat 00:15)
    assert "chat_ttft_p95_s" in JS and "ttft_p95_60s" in JS
    assert "chat_p95_s" not in JS


def test_uses_the_snapshot_fields_from_the_contract():
    for field in ("job_specs", "quote", "agent_model", "explanation", "chat_busy_streams", "busy_60s", "shortfall_kind", "llm_used"):
        assert field in JS, field


def test_timeline_feed_hook_is_exposed():
    # real timelines (tests/fixtures/real_timeline_*.jsonl) are fed through this from the console
    assert "window.brownout = { handle" in JS


def test_receipts_only_read_the_receipts_routes():
    src = (WEB / "receipts.js").read_text(encoding="utf-8")
    routes = set(re.findall(r"/api/\w+", src))
    assert routes == {"/api/runs", "/api/report", "/api/compare", "/api/trace"}, routes
    assert "postJSON" not in src                      # receipts never change anything
