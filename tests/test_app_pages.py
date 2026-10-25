"""How the runtime serves the pages (api/app.py)."""


def test_pages_are_always_revalidated():
    """Sat 19:07: a browser kept an old index.html and world.css; every page file now says no-cache."""
    from fastapi.testclient import TestClient
    from api.app import make_app
    c = TestClient(make_app(object()))
    for path in ("/", "/world.css", "/demo.js"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
