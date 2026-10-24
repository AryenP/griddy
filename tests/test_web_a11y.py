"""Accessibility checks on the pages machine 2 owns (team/2-anuraag.md task 13): WCAG AA contrast for every
text/background pair style.css draws (4.5:1 body text, 3:1 large text and graph marks), live regions so a new
approval is announced, and controls that are named and reachable by keyboard in reading order."""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
CSS = (WEB / "style.css").read_text(encoding="utf-8")
TOKENS = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\b", CSS.split("}", 1)[0]))

BODY, LARGE, MARK = 4.5, 3.0, 3.0

# (foreground, background, minimum, where). A colour is a token name, a #rrggbb literal, or (r, g, b, a) drawn
# over the token after it (a translucent badge or band). Large = 18.66 px bold or 24 px and up.
PAIRS = [
    ("text", "bg", BODY, "body text"),
    ("text", "panel", BODY, "panel text"),
    ("text", "panel2", BODY, "inputs, buttons, chat bubbles, approval cards"),
    ("text", "#1d3b6e", BODY, ".msg.user (your own chat message)"),
    ("muted", "bg", BODY, ".src, .cap, captions on the page"),
    ("muted", "panel", BODY, ".src, .label, .kv b in panels"),
    ("muted", "panel2", BODY, ".msg .meta, .ask-change .was"),
    ("#8fd3ff", "bg", BODY, "links"),
    ("#ffffff", "action", BODY, "button.primary"),
    ("warn", "panel", BODY, ".warn-line, .transcript-label, .state-paused"),
    ("warn", "panel2", BODY, ".warn-line inside approval cards"),
    ("#ffc2c7", "panel", BODY, "li.bad, .bad-text"),
    ("#ffc2c7", "panel2", BODY, ".msg.error .meta"),
    ("#b8f1e9", "panel", BODY, ".state-running, .rtable td.good"),
    ("#b8f1e9", ((47, 181, 165, .22), "panel"), BODY, ".badge.ok"),
    ("warn", ((242, 204, 96, .16), "panel"), BODY, ".badge.warn"),
    ("#ffc2c7", ((255, 90, 103, .22), "panel"), BODY, ".badge.bad"),
    ("#ffd0d0", ((255, 91, 91, .22), "panel"), BODY, ".map-cap span (cap W on its band)"),
    ("bad", "panel", LARGE, ".value.bad, .ttc.bad .ttc-n (large numbers)"),
    ("ok", "panel", LARGE, ".ttc.ok .ttc-n"),
    ("warn", "panel", LARGE, ".ttc.wait .ttc-n"),
    ("job-chat", "panel", BODY, ".map-label b"),
    ("job-train", "panel", BODY, ".map-label b"),
    ("job-batch", "panel", BODY, ".map-label b"),
    ("job-chat", "off", MARK, "map cell: chat runs, next to a deferred slot"),
    ("job-train", "off", MARK, "map cell: train runs"),
    ("job-batch", "off", MARK, "map cell: batch runs"),
    ("price", "panel", MARK, "price line"),
    ("bad", "panel", MARK, "cap band border, over-cap bars"),
    ("#5a7596", "panel", MARK, ".map-bar i (planned watts)"),
    ("action", "panel", MARK, "button.primary's shape"),
]


# Glyphs that carry no information (WCAG 1.4.3 exempts decoration): colour -> where.
DECORATIVE = {"line": ".power-strip .sep, the dot between two numbers"}


def _hex(value: str) -> str:
    """#abc -> #aabbcc, lowercased; anything else unchanged."""
    v = value.strip().lower()
    return "#" + "".join(ch * 2 for ch in v[1:]) if re.fullmatch(r"#[0-9a-f]{3}", v) else v


def rgb(c) -> tuple[float, float, float]:
    if isinstance(c, tuple):                       # ((r, g, b, a), over)
        (r, g, b, a), under = c
        u = rgb(under)
        return tuple(ch / 255 * a + uc * (1 - a) for ch, uc in zip((r, g, b), u))
    h = TOKENS[c] if c in TOKENS else c
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", h), f"not a colour: {c}"
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def luminance(c) -> float:
    lin = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb(c)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_tokens_parsed():
    assert {"bg", "panel", "panel2", "text", "muted", "warn", "bad", "ok", "action", "off"} <= TOKENS.keys()


@pytest.mark.parametrize("fg,bg,minimum,where", PAIRS, ids=[p[3] for p in PAIRS])
def test_contrast(fg, bg, minimum, where):
    assert contrast(fg, bg) >= minimum, f"{where}: {contrast(fg, bg):.2f}:1 < {minimum}:1"


def test_every_text_colour_in_style_css_is_checked():
    # A new `color:` must join PAIRS (with the background it sits on) before it ships.
    checked = {_hex(p[0]) for p in PAIRS} | DECORATIVE.keys()
    used = set()
    for value in re.findall(r"(?<![-\w])color:\s*([^;}]+)", CSS):
        value = value.strip()
        if value.startswith("var(--c"):          # a job's own colour, set per row: the job-* pairs above
            continue
        m = re.fullmatch(r"var\(--([\w-]+)\)", value)
        used.add(m.group(1) if m else _hex(value))
    assert used <= checked, f"unchecked text colours: {sorted(used - checked)}"


# ---------- live regions, names, keyboard order ----------

class Controls(HTMLParser):
    FOCUSABLE = {"a", "button", "input", "select", "textarea"}

    def __init__(self):
        super().__init__()
        self.order: list[dict] = []
        self.live: dict[str, dict] = {}
        self.label_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "label":
            self.label_depth += 1
        if "aria-live" in a and "id" in a:
            self.live[a["id"]] = a
        if tag in self.FOCUSABLE or "tabindex" in a:
            self.order.append({"tag": tag, "in_label": self.label_depth > 0, **a})

    def handle_endtag(self, tag):
        if tag == "label":
            self.label_depth -= 1


def controls(page: str) -> Controls:
    p = Controls()
    p.feed((WEB / page).read_text(encoding="utf-8"))
    return p


@pytest.mark.parametrize("page,board", [("operator.html", "op-approvals"), ("owner.html", "requests")])
def test_new_approvals_are_announced(page, board):
    live = controls(page).live
    assert live.get(board, {}).get("aria-live") == "polite"
    # cards are prepended and then repainted in place (approvals.js): announce a new card, not every repaint
    assert live[board].get("aria-relevant") == "additions"


def test_operator_results_are_announced():
    live = controls("operator.html").live
    assert {"req-result", "ask-result", "adr-result"} <= {k for k, v in live.items() if v["aria-live"] == "polite"}


@pytest.mark.parametrize("page", ["operator.html", "owner.html", "chat.html", "proof.html"])
def test_every_control_has_a_name_and_no_tab_trap(page):
    for c in controls(page).order:
        assert int(c.get("tabindex", 0)) <= 0, f"{page}: positive tabindex on {c.get('id')} breaks reading order"
        if c["tag"] in ("input", "select", "textarea"):
            assert c["in_label"] or c.get("aria-label") or c.get("aria-labelledby"), f"{page}: {c.get('id')} has no name"
        if c["tag"] == "button":
            assert c.get("type") in ("button", "submit"), f"{page}: {c.get('id')} needs an explicit type"


@pytest.mark.parametrize("page,expected", [
    # top to bottom as the page reads: request, dictation, ask, OpenADR (the approval cards are built in between)
    ("operator.html", ["req-text", "req-send", "mic", "ask-text", "ask-send", "adr-text", "adr-send"]),
    ("owner.html", ["owner", "who"]),
])
def test_keyboard_order_follows_the_page(page, expected):
    assert [c.get("id") for c in controls(page).order] == expected


def test_approval_cards_are_keyboard_and_screen_reader_ready():
    js = (WEB / "approvals.js").read_text(encoding="utf-8")
    assert 'ta.setAttribute("aria-label"' in js       # the reply box has a name
    assert 'btn.type = "submit"' in js                # Enter in the form sends the reply
    assert "tabIndex" not in js and "tabindex" not in js
