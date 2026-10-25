"""Who may act (Microsoft HVE Core review, Sat 13:55, fix 1; re-check 20:16: "give the operator its own token, so an
owner's phone cannot answer as the operator"): the venue network has judges' phones on it, so a route that moves a
knob, a cap or an approval needs this machine or a device that joined, and what it may do depends on how it joined.

  - this Mac (a loopback client, or a client on this machine's own address) is the console: trusted for everything;
  - a phone joins once through `GET /join?t=<token>&next=...` (the QR codes from `make qr` carry it), which sets an
    HttpOnly cookie; scripts may send the token in `X-Brownout-Token` instead. The OPERATOR token makes it the
    utility's device (requests, caps, replays, what-ifs, the dispatcher, the over-cap approval); the OWNER token makes
    it a job owner's device (its own job's requests and deadlines). Neither can do the other's part;
  - reads (state, approvals, runs, the WebSocket) and chat stay open.

Each token is `OPERATOR_TOKEN` / `OWNER_TOKEN` from .env, else a random one kept in runs/.operator_token /
runs/.owner_token (gitignored, 0600) so `make qr` and the runtime agree across restarts. They are never logged. In
production each person signs in with Entra ID instead (docs/judging/production.md)."""
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
OWNER_TOKEN_FILE = Path("runs/.owner_token")


def _token(configured: str, path: Path) -> str:
    if configured:
        return configured
    if path.exists() and (tok := path.read_text().strip()):
        return tok
    if path.exists():                                                   # an empty file must not mean "no token" (K12 #6)
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(18)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok


def operator_token() -> str:
    return _token(settings.operator_token, TOKEN_FILE)


def owner_token() -> str:
    return _token(settings.owner_token, OWNER_TOKEN_FILE)


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


def role(request: Request) -> str | None:
    """"machine" (this Mac), "operator" or "owner" (how the device joined), or None (it has not)."""
    if is_this_machine(request):
        return "machine"
    given = request.headers.get(HEADER) or request.cookies.get(COOKIE) or ""
    if given and hmac.compare_digest(given, operator_token()):
        return "operator"
    if given and hmac.compare_digest(given, owner_token()):
        return "owner"
    return None


def joined(request: Request) -> bool:
    return role(request) in ("operator", "owner")


def actor(request: Request) -> str:
    """Where an action came from, for the timeline: the name typed on a page is self-declared, this is not."""
    r = role(request)
    if r == "machine":
        return "this Mac"
    return f"joined {r or 'unknown'} device {request.client.host if request.client else 'unknown'}"


def require(request: Request, roles: tuple[str, ...] = ("operator",)) -> str:
    """This Mac, or a device that joined in one of `roles`; 401 before joining, 403 for the other role."""
    r = role(request)
    if r == "machine" or r in roles:
        return actor(request)
    if r is None:
        raise HTTPException(401, "this device has not joined: open the operator or owner QR code (make qr) on it first")
    raise HTTPException(403, f"this phone joined as the {r}; this is the {' or '.join(roles)}'s to do")


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
