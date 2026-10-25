"""Static checks on every page in web/: no build step, so these catch what a browser would only show at
the demo table (a missing element id, a route the server does not have, an unpinned CDN script, a
hardcoded host, text from the server reaching innerHTML unescaped)."""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
PAGES = sorted(p.name for p in WEB.glob("*.html"))
EXPECTED_PAGES = {"index.html", "chat.html", "owner.html", "operator.html", "proof.html"}
CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"

# HANDOFF.md "API contract" + "Agent and receipts routes"; path parameters normalised to {}.
CONTRACT_ROUTES = {
    "/ws", "/api/state", "/api/policy", "/api/iso", "/api/dispatcher", "/api/jobs/{}", "/api/event",
    "/api/chat", "/api/chat/stream", "/request", "/openadr/event", "/api/approvals",
    "/api/approvals/{}/reply", "/api/explain", "/api/ask", "/api/report", "/api/compare", "/api/runs",
    "/api/trace", "/api/runs/{}/series", "/api/neighbourhood", "/api/replay", "/api/replay/events", "/api/whatif", "/api/whatif/read", "/api/cities",
}


def read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def local_scripts(page: str) -> list[str]:
    return [s for s in re.findall(r'<script src="([^"]+)"', read(page)) if not s.startswith("http")]


def page_js(page: str) -> str:
    return "\n".join(read(s) for s in local_scripts(page))


def all_js() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(WEB.glob("*.js"))}


def templates(src: str) -> list[tuple[str, str]]:
    """(tag, static text) for every template literal in a JS source. A small lexer: skips comments,
    strings and regex literals, and follows ${...} nesting so nested templates are seen on their own."""
    out, i, n = [], 0, len(src)
    stack: list[list] = []     # open templates: [tag, text parts, brace depth inside the current ${}]
    prev = ""                  # last significant character outside strings, for regex detection

    def skip_string(j: int, q: str) -> int:
        j += 1
        while j < n and src[j] != q:
            j += 2 if src[j] == "\\" else 1
        return j + 1

    def skip_regex(j: int) -> int:
        j, cls = j + 1, False
        while j < n:
            c = src[j]
            if c == "\\":
                j += 2
                continue
            if c == "[":
                cls = True
            elif c == "]":
                cls = False
            elif c == "/" and not cls:
                break
            j += 1
        j += 1
        while j < n and src[j].isalpha():
            j += 1
        return j

    def open_template(j: int) -> int:
        k = j - 1
        while k >= 0 and src[k].isspace():
            k -= 1
        m = re.search(r"[\w$.]+$", src[: k + 1])
        stack.append([m.group(0) if m else "", [], 0])
        return read_template(j + 1)

    def read_template(j: int) -> int:
        """Inside a template's static text; returns the index after it closes or after a `${`."""
        t = stack[-1]
        while j < n:
            c = src[j]
            if c == "\\":
                t[1].append(src[j: j + 2])
                j += 2
            elif c == "`":
                out.append((t[0], "".join(t[1])))
                stack.pop()
                return j + 1
            elif c == "$" and src[j + 1: j + 2] == "{":
                t[2] = 1
                return j + 2
            else:
                t[1].append(c)
                j += 1
        raise AssertionError("unterminated template literal")

    while i < n:
        c = src[i]
        if stack and stack[-1][2] > 0 and c in "{}":
            stack[-1][2] += 1 if c == "{" else -1
            if stack[-1][2] == 0:              # back in the template's static text
                i = read_template(i + 1)
                prev = "`"
                continue
            i += 1
            prev = c
            continue
        if src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i < 0 else i
        elif src.startswith("/*", i):
            i = src.index("*/", i) + 2
        elif c in "'\"":
            i = skip_string(i, c)
            prev = c
        elif c == "`":
            i = open_template(i)
            prev = "`"
        elif c == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^" or re.search(r"\breturn\s*$", src[max(0, i - 10): i])):
            i = skip_regex(i)
            prev = "/"
        else:
            if not c.isspace():
                prev = c
            i += 1
    assert not stack, "unterminated template literal"
    return out


def test_every_expected_page_exists():
    assert EXPECTED_PAGES <= set(PAGES), sorted(EXPECTED_PAGES - set(PAGES))


@pytest.mark.parametrize("page", PAGES)
def test_page_is_phone_ready(page):
    h = read(page)
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in h
    assert '<link rel="stylesheet" href="style.css">' in h


@pytest.mark.parametrize("page", PAGES)
def test_only_pinned_chart_js_and_one_webfont_family(page):
    h = read(page)
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', h)
    fonts = [u for u in external if u.startswith("https://fonts.googleapis.com/css2?")]
    assert set(external) - set(fonts) <= {CHART_JS, "https://fonts.googleapis.com", "https://fonts.gstatic.com"}, external
    # brownout-ui: at most one webfont family, with a system fallback in style.css
    assert len({f for u in fonts for f in re.findall(r"family=([^:&]+)", u)}) <= 1, fonts
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", h), "no inline scripts"
    assert not re.search(r"\son[a-z]+=", h), "no inline event handlers"


@pytest.mark.parametrize("page", PAGES)
def test_every_element_the_scripts_use_exists(page):
    js = page_js(page)
    used = set(re.findall(r'\$\("([\w-]+)"\)', js)) | set(re.findall(r'getElementById\("([\w-]+)"\)', js))
    defined = set(re.findall(r'\sid="([\w-]+)"', read(page)))
    assert local_scripts(page)[0] == "common.js", "common.js loads first"
    assert used, f"{page} looks up no elements"
    assert used <= defined, sorted(used - defined)


@pytest.mark.parametrize("name", sorted(all_js()))
def test_calls_only_contract_routes(name):
    js = all_js()[name]
    found = {re.sub(r"\$\{[^}]*\}", "{}", r) for r in re.findall(r"[`\"'](/(?:api/|ws\b|request\b|openadr/)[^`\"'?]*)", js)}
    assert found <= CONTRACT_ROUTES, sorted(found - CONTRACT_ROUTES)


@pytest.mark.parametrize("name", sorted(all_js()))
def test_no_hardcoded_hosts_or_ports(name):
    js = all_js()[name]
    assert not re.search(r"localhost|127\.0\.0\.1|0\.0\.0\.0|https?://|:\d{4}\b", js)


def test_websocket_uses_the_serving_host():
    assert "${location.host}/ws" in read("common.js")


def test_only_set_html_writes_html():
    js = all_js()
    hits = [(n, m.start()) for n, s in js.items() for m in re.finditer(r"\.innerHTML", s)]
    assert [n for n, _ in hits] == ["common.js"], hits
    for n, s in js.items():
        assert not re.search(r"outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function", s), n
        if n != "common.js":
            assert "new SafeHTML" not in s, n
    c = js["common.js"]
    assert re.search(r"function setHTML\(el, safe\) \{\s*if \(!\(safe instanceof SafeHTML\)\) throw", c)
    assert "return esc(v);" in c and "function esc(s)" in c


@pytest.mark.parametrize("name", sorted(all_js()))
def test_markup_only_in_escaping_templates(name):
    """Any template literal that builds markup must be html`...`, which escapes its interpolations."""
    bad = [(tag, text[:60]) for tag, text in templates(all_js()[name])
           if re.search(r"<[a-zA-Z/!]", text) and tag != "html"]
    assert not bad, bad


def test_lexer_sees_nested_and_untagged_templates():
    src = 'const a = html`<b>${x ? `<i>${y}</i>` : "a/b"}</b>`; const r = /[`"\']/g; const s = `<p>${z}</p>`;'
    tags = templates(src)
    assert ("html", "<b></b>") in tags and ("", "<i></i>") in tags and ("", "<p></p>") in tags


def test_operator_neighbourhood_labels_every_number():
    # DECISIONS 05:45: the neighbourhood is SIMULATED except our sites' watts; every number on the page says which
    src = read("operator.js")
    body = src[src.index("function renderNeighbourhood"):src.index("async function toggleNeighbourhood")]
    labels = re.findall(r'<div class="label">([^<]+)</div>', body)
    assert len(labels) == 5 and all(l.endswith(("(simulated)", "(measured)")) for l in labels), labels
    assert [l for l in labels if l.endswith("(measured)")] == ["Our sites (measured)"]
    page = read("operator.html")
    assert 'id="nb"' in page and "SIMULATED" in page and "Simulated neighbourhood" in page
    assert '"/api/neighbourhood"' in src and 'd.simulated === true' in src
