"""scripts/qr.py: one QR per phone page on PUBLIC_URL, and a refusal when a phone could not open it."""
import importlib.util
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("qr_script", ROOT / "scripts" / "qr.py")
qr = importlib.util.module_from_spec(_spec)
sys.modules["qr_script"] = qr
_spec.loader.exec_module(qr)


def test_one_url_per_phone_page_and_the_pages_exist():
    got = qr.urls("http://192.168.1.10:8080/")
    assert [u for _, u, _ in got] == ["http://192.168.1.10:8080/chat", "http://192.168.1.10:8080/owner.html",
                                      "http://192.168.1.10:8080/operator.html"]
    for _, path, _ in qr.PAGES:   # /chat is served by the API (chat.html); the others are files in web/
        assert (ROOT / "web" / (path.lstrip("/") if path.endswith(".html") else "chat.html")).exists(), path


@pytest.mark.parametrize("bad", ["http://localhost:8080", "http://127.0.0.1:8080", "http://[::1]:8080", "", "192.168.1.10:8080"])
def test_refuses_urls_a_phone_cannot_open(bad):
    with pytest.raises(ValueError):
        qr.urls(bad)


def test_png_and_terminal_code(tmp_path):
    url = "http://192.168.1.10:8080/chat"
    png = qr.save_png(url, tmp_path / "qr" / "chat.png")
    with Image.open(png) as im:
        assert im.size[0] == im.size[1] and im.size[0] > 100
    text = qr.terminal(url)
    assert len(text.splitlines()) > 10


def test_main_fails_without_a_reachable_public_url(monkeypatch, tmp_path, capsys):
    import core.config
    monkeypatch.setattr(core.config.settings, "public_url", "http://localhost:8080")
    assert qr.main(["--out", str(tmp_path)]) == 1
    assert "LAN IP" in capsys.readouterr().err
    monkeypatch.setattr(core.config.settings, "public_url", "http://192.168.1.10:8080")
    assert qr.main(["--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["chat.png", "operator.png", "owner.png"]
