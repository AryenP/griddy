"""Dashboard-specific static checks (the per-page checks for every page are in test_web_pages.py)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
HTML = (WEB / "info.html").read_text(encoding="utf-8")        # the dashboard moved to info.html (Sat 16:30)
JS = (WEB / "app.js").read_text(encoding="utf-8")
WORLD_HTML = (WEB / "index.html").read_text(encoding="utf-8")  # the judge's page: the 3D grid world
DEMO_JS = (WEB / "demo.js").read_text(encoding="utf-8")
WORLD_JS = (WEB / "world.js").read_text(encoding="utf-8")


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


def test_the_judge_page_is_the_3d_world_and_its_dock():
    """index.html (Sat 16:30): the grid as a 3D world drawn without a library, four choices and four numbers."""
    assert re.findall(r'<script src="([^"]+)"', WORLD_HTML) == ["common.js", "world.js", "demo.js"]
    assert '<canvas id="world"' in WORLD_HTML and 'href="/info.html"' in WORLD_HTML
    assert "simulated" not in WORLD_HTML.lower() + DEMO_JS.lower()
    assert set(re.findall(r'postJSON\(\s*[`"](/api/[\w/${}]+)', DEMO_JS)) <= {"/api/replay", "/api/jobs/${job}", "/api/whatif", "/api/whatif/read"}
    assert "prefers-reduced-motion" in WORLD_JS and "REDUCE" in WORLD_JS          # no motion for those who ask
    assert "ev.data_source" in DEMO_JS and "ev.report_url" in DEMO_JS and "estimate" in DEMO_JS
    assert "measured by powermetrics" in WORLD_HTML + DEMO_JS


def test_world_draws_only_what_it_is_given():
    """Every quantity in the 3D world comes from World.set(): the fuel mix, served and needed, our watts."""
    for field in ("mix", "served", "needed", "ours_w", "baseline_w", "alert", "campus"):
        assert f"d.{field}" in WORLD_JS or f"S.data.{field}" in WORLD_JS, field
    assert not re.search(r"Math\.random\(\)\s*\*\s*\d+\s*[,)]", WORLD_JS.split("function smoke")[0].split("function drawPlant")[0])


def test_a_judge_can_break_any_part_and_the_page_says_what_if():
    """Sat 17:19: a click on a plant, the substation or the city opens a confirm card; the fault is labelled what-if,
    sized from the grid at that moment, and also reachable from the keyboard (the Break a part menu)."""
    assert "World.onPick" in DEMO_JS and "onPick" in WORLD_JS and "targets()" in WORLD_JS
    assert 'id="w-break-btn"' in WORLD_HTML and 'id="w-pop"' in WORLD_HTML and 'role="dialog"' in WORLD_HTML
    assert DEMO_JS.count("What-if:") >= 3 and "what-if" in WORLD_JS
    assert "Without Griddy" in WORLD_HTML and "With Griddy" in WORLD_HTML


def test_the_replay_says_where_its_hours_came_from():
    """Sat 17:19 (Aryen: the data must be live, not a canned replay): fetched live from api.eia.gov, or the evidence
    copy and why; and the software sees each hour only once it has ended."""
    assert "api.eia.gov" in DEMO_JS and "evidence copy" in DEMO_JS and "once it has ended" in DEMO_JS
    assert "d.hour_ending" in DEMO_JS


def test_a_judge_can_say_how_it_breaks_and_confirms_the_reading_first():
    """Sat 17:27: words go to /api/whatif/read (a pattern, then the model); the page shows the reading with its real
    size and breaks nothing until the judge confirms. Griddy's executed actions show as they happen."""
    assert 'id="w-pop-in"' in WORLD_HTML and "/api/whatif/read" in DEMO_JS and "Break it like that" in DEMO_JS
    assert 'case "action"' in DEMO_JS and "Griddy acts" in DEMO_JS


def test_the_city_map_says_what_is_real_and_what_is_drawn():
    """Sat 19:59: clicking the city flies into one real square of it, drawn 1:1 from OpenStreetMap (/api/cities/{id}/map):
    buildings at their heights, streets, power lines, hospitals. Homes dark: the grid's real served / needed; which blocks
    go dark and the feeder routing are illustrative, and the footer says so, with how many heights are estimated."""
    assert "/api/cities/${city.id}/map" in DEMO_JS and "openCity" in DEMO_JS and 'id="w-back"' in WORLD_HTML
    assert "drawn 1:1" in DEMO_JS and "illustrative" in DEMO_JS and "heights estimated" in DEMO_JS
    state = WORLD_JS[WORLD_JS.index("function cityState"):WORLD_JS.index("function prism")]
    assert "d.served" in state and "d.needed" in state and "d.with_mw" in state
    assert "function drawTransition" in WORLD_JS and "REDUCE ? null" in WORLD_JS          # the fly-in, none if reduced motion


def test_the_logo_loader_shows_while_the_page_loads_and_always_goes_away():
    """Sat 19:40 (Aryen): a G drawn as a power line, a red node healed by a mint pulse, the wordmark in Inter. It is
    inline SVG and CSS (nothing to download), fades after the first snapshot, and CSS fades it at 6 s if JS never runs."""
    assert WORLD_HTML.index('id="w-load"') < WORLD_HTML.index('<header class="w-top">')     # first thing painted
    assert 'role="status"' in WORLD_HTML and "<svg" in WORLD_HTML and 'class="g-fault"' in WORLD_HTML
    css = (WEB / "world.css").read_text()
    assert "w-load-out 0.4s ease 6s forwards" in css and ".w-load * { animation: none !important; }" in css
    assert "hideLoader();" in DEMO_JS and "setTimeout(hideLoader, 4000)" in DEMO_JS
