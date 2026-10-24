"""Static checks on the dashboard: no build step, so these catch the mistakes a browser would only
show at the demo table (a missing element id, an unpinned CDN script, a hardcoded host)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "app.js").read_text(encoding="utf-8")


def test_every_element_the_script_uses_exists():
    used = set(re.findall(r'\$\("([\w-]+)"\)', JS))
    defined = set(re.findall(r'id="([\w-]+)"', HTML))
    assert used, "app.js looks up no elements"
    assert used <= defined, sorted(used - defined)


def test_external_scripts_are_pinned_to_an_exact_version():
    srcs = re.findall(r'<script src="(https?://[^"]+)"', HTML)
    assert srcs, "Chart.js should come from a CDN"
    for s in srcs:
        assert re.search(r"/\d+\.\d+\.\d+/", s), s


def test_no_hardcoded_hosts_or_ports():
    # the page talks to whatever served it: /ws and /api/* on location.host
    assert not re.search(r"localhost|127\.0\.0\.1|:\d{4}\b", JS)
    assert "location.host" in JS


def test_posts_only_to_contract_routes():
    routes = set(re.findall(r'post\("(/api/[\w/]+)"', JS))
    assert routes <= {"/api/iso", "/api/policy", "/api/dispatcher"}, routes
