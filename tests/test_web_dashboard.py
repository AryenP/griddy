"""Dashboard-specific static checks (the per-page checks for every page are in test_web_pages.py)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "app.js").read_text(encoding="utf-8")


def test_dashboard_loads_its_scripts_and_no_external_ones():
    # the dispatch map is plain HTML/CSS/SVG (web/map.js): no chart library to fetch when the venue network drops
    assert re.findall(r'<script src="([^"]+)"', HTML) == ["common.js", "map.js", "trace.js", "app.js", "receipts.js"]
    assert '<link rel="stylesheet" href="dashboard.css">' in HTML


def test_posts_only_to_contract_routes():
    routes = set(re.findall(r'post\("(/api/[\w/]+)"', JS))
    assert routes <= {"/api/iso", "/api/policy", "/api/dispatcher", "/api/replay"}, routes


def test_chat_sla_is_time_to_first_token():
    # policy.sla.chat_p95_s no longer exists (HANDOFF.md, Sat 00:15)
    assert "chat_ttft_p95_s" in JS and "ttft_p95_60s" in JS
    assert "chat_p95_s" not in JS


def test_uses_the_snapshot_fields_from_the_contract():
    for field in ("job_specs", "quote", "agent_model", "explanation", "chat_busy_streams", "busy_60s", "shortfall_kind", "llm_used",
                  "power_history", "cap_events", "background_w"):
        assert field in JS, field


def test_timeline_feed_hook_is_exposed():
    # real timelines (tests/fixtures/real_timeline_*.jsonl) are fed through this from the console
    assert "window.brownout = { handle" in JS


def test_receipts_only_read_the_receipts_routes():
    src = (WEB / "receipts.js").read_text(encoding="utf-8")
    routes = set(re.findall(r"/api/\w+", src))
    assert routes == {"/api/runs", "/api/report", "/api/compare", "/api/trace"}, routes
    assert "postJSON" not in src                      # receipts never change anything


TRACE = (WEB / "trace.js").read_text(encoding="utf-8")


def test_trace_draws_only_measured_samples():
    # gaps stay gaps: no watts are drawn for seconds nobody measured, and nothing is interpolated or smoothed
    assert "GAP_S" in TRACE and "t - pts[i - 1][0] > GAP_S" in TRACE
    assert not any(w in TRACE for w in ("interpolat(", "smooth(", "Math.random"))


def test_within_or_over_uses_the_reporters_rule():
    # agent/reporter.py ROLLING_S: compliance is the trailing 10-s mean at or under the cap
    assert "ROLL_S = 10" in TRACE
    assert "ROLLING_S = 10.0" in (WEB.parent / "agent" / "reporter.py").read_text(encoding="utf-8")


def test_map_slots_are_pinnable_by_click_and_keyboard():
    assert 'data-slot="${i}"' in (WEB / "map.js").read_text(encoding="utf-8")
    assert 'id="map" class="map" tabindex="0"' in HTML
    assert "ArrowLeft" in JS and "Escape" in JS


def test_no_global_name_is_defined_twice_across_the_page_scripts():
    # the page's scripts share one global scope: a second `function renderTrace` silently replaced the first
    seen: dict[str, str] = {}
    for src in re.findall(r'<script src="([^"]+)"', HTML):
        for name in re.findall(r"^(?:async )?(?:function|const|let|class) ([A-Za-z_$][\w$]*)", (WEB / src).read_text(encoding="utf-8"), re.M):
            assert name not in seen, f"{name} is defined in both {seen[name]} and {src}"
            seen[name] = src


def test_replay_panel_shows_real_data_with_its_sources_and_labels_estimates():
    """Sat 15:40: the simulated neighbourhood is gone; replays of real emergencies show the operator's own data (EIA-930)
    and the official report's line for every alert and impact; scale figures say "estimate"."""
    assert "simulated" not in HTML.lower()
    assert "Replay a real grid emergency" in HTML and "recorded grid data" in HTML
    assert "ev.data_source" in JS and "a.source" in JS and "i.source" in JS and "ev.report_url" in JS
    assert JS.count('class="d-sim">estimate') >= 2          # the operator's-scale line and ERCOT right now
    assert 'post("/api/replay", { action: "start", event:' in JS
