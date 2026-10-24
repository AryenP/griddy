"""QR codes for the judge's phone: the chat page, the job owner's console and the grid operator's console on
PUBLIC_URL (.env). Printed in the terminal and saved as PNGs under reports/qr/ for the table cards.

    make qr        # = uv run python scripts/qr.py [--out DIR]

PUBLIC_URL must be an address a phone on the same network can open: this machine's LAN IP, not localhost
(`make preflight` checks that it matches)."""
from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path
from urllib.parse import urlparse

import qrcode

ROOT = Path(__file__).resolve().parents[1]
PAGES = [("chat", "/chat", "use the service"), ("owner", "/owner.html", "you own a job"),
         ("operator", "/operator.html", "you are the utility")]


def urls(public_url: str) -> list[tuple[str, str, str]]:
    """(name, url, role) for every phone page. Raises ValueError when a phone could not open PUBLIC_URL."""
    u = urlparse(public_url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"PUBLIC_URL {public_url!r} is not an http(s) URL")
    try:
        loopback = ipaddress.ip_address(u.hostname).is_loopback
    except ValueError:
        loopback = u.hostname == "localhost"
    if loopback:
        raise ValueError(f"PUBLIC_URL {public_url!r} points at this machine's loopback, which a phone cannot open")
    base = public_url.strip().rstrip("/")
    return [(name, base + path, role) for name, path, role in PAGES]


def save_png(url: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(url, border=2).save(path)
    return path


def terminal(url: str) -> str:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    lines: list[str] = []

    class _Out:
        def write(self, s: str) -> None:
            lines.append(s)

        def flush(self) -> None:
            pass

    qr.print_ascii(out=_Out(), invert=True)
    return "".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="make qr")
    ap.add_argument("--out", default=str(ROOT / "reports" / "qr"), help="where the PNGs go")
    args = ap.parse_args(argv)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.config import settings

    try:
        pages = urls(settings.public_url)
    except ValueError as e:
        print(f"FAIL {e}\n  -> set PUBLIC_URL=http://<this machine's LAN IP>:<PORT> in .env (make preflight shows it)",
              file=sys.stderr)
        return 1
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # the QR blocks on a Windows console
    out = Path(args.out)
    for name, url, role in pages:
        png = save_png(url, out / f"{name}.png")
        print(f"\n{name}: {role}\n{url}\n{terminal(url)}saved {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
