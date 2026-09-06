"""Optional bearer-style authentication for the packaged local desktop API."""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

TOKEN_ENV = "COMIC_AGENT_LOCAL_TOKEN"
TOKEN_HEADER = "x-comic-agent-token"
TOKEN_QUERY = "token"
PUBLIC_PATHS = frozenset({"/health", "/livez", "/readyz"})
ALLOWED_WEBSOCKET_ORIGINS = frozenset(
    {
        "",
        "null",
        "file://",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }
)


def configured_token(environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    return str(source.get(TOKEN_ENV, "") or "").strip()


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS


def is_token_valid(expected: str, provided: str | None) -> bool:
    """Fail open only when no token is configured (development compatibility)."""

    if not expected:
        return True
    return bool(provided) and hmac.compare_digest(expected, provided)


def request_token(headers: Mapping[str, str], query_token: str | None = None) -> str | None:
    return headers.get(TOKEN_HEADER) or query_token


def is_allowed_websocket_origin(origin: str | None) -> bool:
    """Allow only the local desktop shell and the Vite development origin.

    Non-browser websocket clients commonly omit ``Origin``; an absent value
    remains allowed because the token check is the authentication boundary.
    Browser clients always send an origin, so an unrelated website cannot use
    a user's ambient local credentials to open a project socket.
    """

    return (origin or "").strip().lower() in ALLOWED_WEBSOCKET_ORIGINS
