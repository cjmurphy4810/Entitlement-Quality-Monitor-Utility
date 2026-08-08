"""Authentication primitives for the CTADMIN dashboard."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import OrderedDict, deque
from dataclasses import dataclass

from fastapi import HTTPException, status
from starlette.requests import Request

from eqm.config import Settings

SESSION_COOKIE_NAME = "ctadmin_session"


class InvalidSession(Exception):  # noqa: N818 - public interface name from the dashboard contract
    """Raised when a session token cannot be trusted."""


@dataclass(frozen=True)
class SessionPrincipal:
    """The authenticated identity carried by a signed CTADMIN session."""

    username: str
    csrf_token: str
    persona_id: str
    nonce: str
    expires_at: int | None = None

    @property
    def subject(self) -> str:
        """Return the token subject using conventional authentication terminology."""
        return self.username


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_b64decode(value: str) -> bytes:
    try:
        encoded = value.encode("ascii")
        decoded = base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))
    except (UnicodeEncodeError, ValueError) as exc:
        raise InvalidSession from exc
    if _urlsafe_b64encode(decoded) != value:
        raise InvalidSession
    return decoded


class SessionCodec:
    """Encode and validate short-lived, HMAC-signed session principals."""

    def __init__(self, secret: str, ttl_seconds: int = 28_800) -> None:
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    def encode(
        self,
        username: str,
        *,
        now: int | None = None,
        persona_id: str = "ctadmin",
        csrf_token: str | None = None,
        nonce: str | None = None,
        expires_at: int | None = None,
    ) -> str:
        issued_at = int(time.time()) if now is None else now
        expiry = issued_at + self._ttl_seconds if expires_at is None else expires_at
        if isinstance(expiry, bool) or not isinstance(expiry, int) or expiry <= issued_at:
            raise InvalidSession
        payload = {
            "sub": username,
            "exp": expiry,
            "csrf": csrf_token or secrets.token_urlsafe(32),
            "persona_id": persona_id,
            "nonce": nonce or secrets.token_urlsafe(16),
        }
        encoded_payload = _urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signature = hmac.new(self._secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded_payload}.{_urlsafe_b64encode(signature)}"

    def decode(self, token: str, *, now: int | None = None) -> SessionPrincipal:
        try:
            encoded_payload, encoded_signature = token.split(".")
            encoded_payload_bytes = encoded_payload.encode("ascii")
            supplied_signature = _urlsafe_b64decode(encoded_signature)
        except (AttributeError, UnicodeEncodeError, ValueError, InvalidSession) as exc:
            raise InvalidSession from exc

        expected_signature = hmac.new(self._secret, encoded_payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise InvalidSession

        try:
            payload = json.loads(_urlsafe_b64decode(encoded_payload))
        except (UnicodeDecodeError, json.JSONDecodeError, InvalidSession) as exc:
            raise InvalidSession from exc
        if not isinstance(payload, dict):
            raise InvalidSession

        username = payload.get("sub")
        expires_at = payload.get("exp")
        csrf_token = payload.get("csrf")
        persona_id = payload.get("persona_id")
        nonce = payload.get("nonce")
        if (
            not all(
                isinstance(value, str) and value
                for value in (username, csrf_token, persona_id, nonce)
            )
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
        ):
            raise InvalidSession
        current_time = int(time.time()) if now is None else now
        if expires_at <= current_time:
            raise InvalidSession
        return SessionPrincipal(username, csrf_token, persona_id, nonce, expires_at)


def require_ctadmin_settings(settings: Settings) -> Settings:
    """Return configured settings or signal that CTADMIN is unavailable."""
    session_secret = settings.ctadmin_session_secret
    if (
        not settings.ctadmin_username
        or settings.ctadmin_password is None
        or session_secret is None
        or not session_secret.get_secret_value().strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CTADMIN is not configured",
        )
    return settings


def validate_credentials(username: str, password: str, settings: Settings) -> bool:
    """Compare submitted credentials without short-circuiting either comparison."""
    configured = require_ctadmin_settings(settings)
    username_matches = hmac.compare_digest(
        username.encode("utf-8"), configured.ctadmin_username.encode("utf-8")
    )
    password_matches = hmac.compare_digest(
        password.encode("utf-8"), configured.ctadmin_password.get_secret_value().encode("utf-8")
    )
    return username_matches and password_matches


def get_principal(
    request: Request, settings: Settings, *, now: int | None = None
) -> SessionPrincipal | None:
    """Read and verify the CTADMIN session cookie, returning no principal if invalid."""
    configured = require_ctadmin_settings(settings)
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token is None:
        return None
    codec = SessionCodec(
        configured.ctadmin_session_secret.get_secret_value(),
        configured.ctadmin_session_ttl_seconds,
    )
    try:
        return codec.decode(token, now=now)
    except InvalidSession:
        return None


def require_principal(
    request: Request, settings: Settings, *, now: int | None = None
) -> SessionPrincipal:
    """Return the signed session principal or reject unauthenticated requests."""
    principal = get_principal(request, settings, now=now)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return principal


async def validate_csrf(request: Request, principal: SessionPrincipal) -> None:
    """Validate a JSON header or HTML form token against the session token."""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        submitted_token = request.headers.get("x-csrf-token")
    else:
        submitted_token = (await request.form()).get("csrf_token")
    if not isinstance(submitted_token, str) or not hmac.compare_digest(
        submitted_token.encode("utf-8"), principal.csrf_token.encode("utf-8")
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


class LoginThrottle:
    """Bound repeated login failures in memory by normalized user and client address."""

    def __init__(
        self,
        limit: int = 5,
        window_seconds: int = 300,
        max_keys: int = 2048,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.failures: OrderedDict[str, deque[float]] = OrderedDict()

    def _recent(self, key: str) -> deque[float]:
        recent = self.failures.get(key)
        if recent is None:
            while len(self.failures) >= self.max_keys:
                self.failures.popitem(last=False)
            recent = deque()
            self.failures[key] = recent
        else:
            self.failures.move_to_end(key)
        return recent

    def check(self, key: str, now: float) -> None:
        recent = self._recent(key)
        while recent and recent[0] <= now - self.window_seconds:
            recent.popleft()
        if len(recent) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts",
            )

    def record_failure(self, key: str, now: float) -> None:
        self._recent(key).append(now)

    def clear(self, key: str) -> None:
        self.failures.pop(key, None)


def login_throttle_key(username: str, request: Request) -> str:
    """Return the normalized username and client address throttle key."""
    address = request.client.host if request.client else "unknown"
    return f"{username.strip().casefold()}:{address}"


class MutationThrottle:
    """Bound mutation attempts per signed session and client address in memory."""

    def __init__(self, limit: int = 5, window_seconds: int = 60, max_keys: int = 2048) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self.attempts: OrderedDict[str, deque[float]] = OrderedDict()

    def check_and_record(self, key: str, now: float) -> None:
        recent = self.attempts.get(key)
        if recent is None:
            while len(self.attempts) >= self.max_keys:
                self.attempts.popitem(last=False)
            recent = deque()
            self.attempts[key] = recent
        else:
            self.attempts.move_to_end(key)
        while recent and recent[0] <= now - self.window_seconds:
            recent.popleft()
        if len(recent) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many mutation attempts",
            )
        recent.append(now)


def mutation_throttle_key(principal: SessionPrincipal, request: Request) -> str:
    """Return a key tied to both a signed-session nonce and its client address."""
    address = request.client.host if request.client else "unknown"
    return f"{principal.nonce}:{address}"
