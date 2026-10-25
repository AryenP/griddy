"""The operator's phone page (operator.html, operator.js) since Sat 19:50: the simulated neighbourhood is gone (its route
was removed at 16:01 and the page still called it); a judge replays a REAL emergency and breaks a part in their own
words, with every number labelled by where it comes from."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
HTML = (WEB / "operator.html").read_text(encoding="utf-8")
JS = (WEB / "operator.js").read_text(encoding="utf-8")


def test_no_neighbourhood_left_and_only_live_routes_are_called():
    assert "neighbourhood" not in (HTML + JS).lower() and "simulated" not in HTML.lower()
    posts = set(re.findall(r'postJSON\(\s*[`"](/[\w/${}]+)', JS))
    assert {"/api/replay", "/api/whatif/read", "/api/whatif"} <= posts and "/api/neighbourhood" not in posts
    assert 'getJSON("/api/replay/events")' in JS


def test_the_replay_panel_says_where_each_number_comes_from():
    body = JS[JS.index("function renderReplay"):JS.index("async function toggleReplay")]
    labels = re.findall(r'<div class="label">([^<$]+)', body)
    assert labels == ["Hour (", "Served / needed", "Our sites (measured)", "With Griddy (estimate)"], labels
    assert "EIA-930" in body and "api.eia.gov" in body and "the last hour that has ended" in body


def test_a_fault_is_read_back_before_anything_breaks():
    assert 'id="wi-go"' in HTML and "hidden" in HTML.split('id="wi-go"')[1][:40]       # no confirm button until a reading
    read = JS[JS.index("async function readFault"):JS.index("async function breakIt")]
    assert "/api/whatif/read" in read and '$("wi-go").hidden = false' in read and "/api/whatif\"" not in read
    assert "what-if" in HTML and "Without Griddy" in JS and "With Griddy (estimate)" in JS
