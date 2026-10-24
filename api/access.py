"""Who may act (Microsoft HVE Core review, Sat 13:55, fix 1): the venue network has judges' phones on it, so a
route that moves a knob, a cap or an approval needs this machine or a device that joined.

  - this Mac (a loopback client, or a client on this machine's own address) is the operator console: trusted;
  - any other device joins once through `GET /join?t=<token>&next=/operator.html` (the QR codes carry it), which
    sets an HttpOnly cookie; scripts may send the token in `X-Brownout-Token` instead;
  - reads (state, approvals, runs, the WebSocket) and chat stay open.

The token is `OPERATOR_TOKEN` from .env, else a random one kept in runs/.operator_token (gitignored, 0600) so
`make qr` and the runtime agree across restarts. It is never logged. In production each person signs in with
Entra ID instead (docs/judging/production.md)."""
from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import HTTPException, Request

from core.config import settings

COOKIE = "brownout_op"
HEADER = "x-brownout-token"
TOKEN_FILE = Path("runs/.operator_token")


def operator_token() -> str:
    if settings.operator_token:
        return settings.operator_token
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(18)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok


def is_this_machine(request: Request) -> bool:
    """A loopback client, or one connecting from the address it connected to (this Mac opening its LAN URL)."""
    host = request.client.host if request.client else ""
    try:
        if ipaddress.ip_address(host).is_loopback:
            return True
    except ValueError:
        return False
    server = request.scope.get("server") or ("", 0)
    return bool(server[0]) and host == server[0]


def joined(request: Request) -> bool:
    tok = operator_token()
    given = request.headers.get(HEADER) or request.cookies.get(COOKIE) or ""
    return hmac.compare_digest(given, tok)


def actor(request: Request) -> str:
    """Where an action came from, for the timeline: the name typed on a page is self-declared, this is not."""
    if is_this_machine(request):
        return "this Mac"
    return f"joined device {request.client.host if request.client else 'unknown'}"


def require(request: Request) -> str:
    if is_this_machine(request) or joined(request):
        return actor(request)
    raise HTTPException(401, "this device has not joined: open the operator or owner QR code (make qr) on it first")


class RateLimit:
    """At most `n` calls per `per_s` seconds per client, for routes that each cost a paid model call
    (HVE Core review: denial of service on /request and /api/ask)."""

    def __init__(self, n: int, per_s: float):
        self.n, self.per_s = n, per_s
        self.calls: dict[str, deque[float]] = defaultdict(deque)

    def check(self, request: Request) -> None:
        key = request.client.host if request.client else ""
        now, q = time.monotonic(), self.calls[key]
        while q and q[0] <= now - self.per_s:
            q.popleft()
        if len(q) >= self.n:
            raise HTTPException(429, f"at most {self.n} requests per {self.per_s:.0f} s from one device; try again shortly")
        q.append(now)
