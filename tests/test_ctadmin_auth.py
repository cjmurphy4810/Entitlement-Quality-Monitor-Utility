import json

import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from eqm.config import Settings


def make_request(
    *,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    if cookies:
        raw_headers.append((b"cookie", "; ".join(f"{key}={value}" for key, value in cookies.items()).encode()))
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": raw_headers,
         "client": ("203.0.113.7", 12345)},
        receive,
    )


def configured_settings(monkeypatch) -> Settings:
    monkeypatch.setenv("EQM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("EQM_CTADMIN_USERNAME", "demo-admin")
    monkeypatch.setenv("EQM_CTADMIN_PASSWORD", "correct-horse-battery-staple")
    monkeypatch.setenv("EQM_CTADMIN_SESSION_SECRET", "test-session-secret-at-least-32-bytes")
    monkeypatch.setenv("EQM_CTADMIN_SECURE_COOKIES", "0")
    return Settings()


def test_ctadmin_settings_are_optional_by_default(monkeypatch):
    monkeypatch.setenv("EQM_BEARER_TOKEN", "test-token")
    monkeypatch.delenv("EQM_CTADMIN_USERNAME", raising=False)
    monkeypatch.delenv("EQM_CTADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("EQM_CTADMIN_SESSION_SECRET", raising=False)

    settings = Settings()

    assert settings.ctadmin_username is None
    assert settings.ctadmin_password is None
    assert settings.ctadmin_session_secret is None
    assert settings.ctadmin_secure_cookies is True


@pytest.mark.parametrize("secret", ["", "short-secret", " " * 32])
def test_settings_rejects_blank_or_short_ctadmin_session_secret(monkeypatch, secret):
    monkeypatch.setenv("EQM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("EQM_CTADMIN_SESSION_SECRET", secret)

    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_whitespace_only_secretstr_session_secret():
    with pytest.raises(ValidationError):
        Settings(bearer_token="test-token", ctadmin_session_secret=SecretStr(" " * 32))


def test_session_codec_round_trips_signed_principal():
    from eqm.ctadmin.auth import SessionCodec

    codec = SessionCodec("a-session-secret-that-is-long-enough", ttl_seconds=3600)

    token = codec.encode("demo-admin", now=1_700_000_000, persona_id="ops")
    principal = codec.decode(token, now=1_700_000_001)

    assert principal.username == "demo-admin"
    assert principal.persona_id == "ops"
    assert principal.csrf_token


def test_session_codec_rejects_expired_token():
    from eqm.ctadmin.auth import InvalidSession, SessionCodec

    codec = SessionCodec("a-session-secret-that-is-long-enough", ttl_seconds=300)
    token = codec.encode("demo-admin", now=1_700_000_000)

    with pytest.raises(InvalidSession):
        codec.decode(token, now=1_700_000_300)


def test_session_codec_rejects_tampered_token():
    from eqm.ctadmin.auth import InvalidSession, SessionCodec

    codec = SessionCodec("a-session-secret-that-is-long-enough", ttl_seconds=3600)
    token = codec.encode("demo-admin", now=1_700_000_000)

    with pytest.raises(InvalidSession):
        codec.decode(token[:-1] + ("a" if token[-1] != "a" else "b"), now=1_700_000_001)


def test_session_codec_rejects_malformed_non_ascii_token():
    from eqm.ctadmin.auth import InvalidSession, SessionCodec

    codec = SessionCodec("a-session-secret-that-is-long-enough", ttl_seconds=3600)

    with pytest.raises(InvalidSession):
        codec.decode("☃.dGVzdA", now=1_700_000_001)


def test_require_ctadmin_settings_returns_service_unavailable_when_unconfigured(monkeypatch):
    from eqm.ctadmin.auth import require_ctadmin_settings

    monkeypatch.setenv("EQM_BEARER_TOKEN", "test-token")
    monkeypatch.delenv("EQM_CTADMIN_USERNAME", raising=False)
    monkeypatch.delenv("EQM_CTADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("EQM_CTADMIN_SESSION_SECRET", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        require_ctadmin_settings(Settings())

    assert exc_info.value.status_code == 503


def test_get_principal_reads_a_valid_session_cookie(monkeypatch):
    from eqm.ctadmin.auth import SessionCodec, get_principal

    settings = configured_settings(monkeypatch)
    token = SessionCodec(settings.ctadmin_session_secret.get_secret_value()).encode(
        "demo-admin", now=1_700_000_000
    )

    principal = get_principal(
        make_request(cookies={"ctadmin_session": token}), settings, now=1_700_000_001
    )

    assert principal is not None
    assert principal.username == "demo-admin"


def test_require_principal_rejects_a_missing_session_cookie(monkeypatch):
    from eqm.ctadmin.auth import require_principal

    with pytest.raises(HTTPException) as exc_info:
        require_principal(make_request(), configured_settings(monkeypatch))

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_validate_csrf_accepts_matching_json_header():
    from eqm.ctadmin.auth import SessionPrincipal, validate_csrf

    principal = SessionPrincipal("demo-admin", "csrf-value", "ops", "nonce")
    request = make_request(
        headers={"content-type": "application/json", "x-csrf-token": "csrf-value"},
        body=json.dumps({"action": "save"}).encode(),
    )

    await validate_csrf(request, principal)


@pytest.mark.asyncio
async def test_validate_csrf_rejects_a_missing_form_token():
    from eqm.ctadmin.auth import SessionPrincipal, validate_csrf

    principal = SessionPrincipal("demo-admin", "csrf-value", "ops", "nonce")
    request = make_request(
        headers={"content-type": "application/x-www-form-urlencoded"}, body=b"action=save"
    )

    with pytest.raises(HTTPException) as exc_info:
        await validate_csrf(request, principal)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "body"),
    [
        ({"content-type": "application/json", "x-csrf-token": "tøkén"}, b"{}"),
        ({"content-type": "application/x-www-form-urlencoded"}, b"csrf_token=t%C3%B8k%C3%A9n"),
    ],
)
async def test_validate_csrf_rejects_non_ascii_submissions(headers, body):
    from eqm.ctadmin.auth import SessionPrincipal, validate_csrf

    principal = SessionPrincipal("demo-admin", "csrf-value", "ops", "nonce")

    with pytest.raises(HTTPException) as exc_info:
        await validate_csrf(make_request(headers=headers, body=body), principal)

    assert exc_info.value.status_code == 403


def test_validate_credentials_requires_both_configured_values(monkeypatch):
    from eqm.ctadmin.auth import validate_credentials

    settings = configured_settings(monkeypatch)

    assert validate_credentials("demo-admin", "correct-horse-battery-staple", settings) is True
    assert validate_credentials("demo-admin", "incorrect", settings) is False
    assert validate_credentials("other-admin", "correct-horse-battery-staple", settings) is False


def test_validate_credentials_rejects_non_ascii_input(monkeypatch):
    from eqm.ctadmin.auth import validate_credentials

    settings = configured_settings(monkeypatch)

    assert validate_credentials("démo-admin", "correct-horse-battery-staple", settings) is False
    assert validate_credentials("demo-admin", "pässword", settings) is False


def test_login_throttle_locks_out_sixth_attempt_and_clears_after_success():
    from eqm.ctadmin.auth import LoginThrottle

    throttle = LoginThrottle()
    key = "demo-admin:203.0.113.7"
    for attempt in range(5):
        throttle.check(key, now=float(attempt))
        throttle.record_failure(key, now=float(attempt))

    with pytest.raises(HTTPException) as exc_info:
        throttle.check(key, now=5.0)

    assert exc_info.value.status_code == 429
    throttle.clear(key)
    throttle.check(key, now=5.0)


def test_login_throttle_key_normalizes_username_and_uses_client_address():
    from eqm.ctadmin.auth import login_throttle_key

    key = login_throttle_key("  DEMO-Admin  ", make_request())

    assert key == "demo-admin:203.0.113.7"


def test_mutation_throttle_is_per_session_ip_and_memory_bounded():
    """A hot mutation session must be rejected without growing the key store forever."""
    from eqm.ctadmin.auth import MutationThrottle

    throttle = MutationThrottle(limit=2, window_seconds=60, max_keys=2)
    throttle.check_and_record("session-a:203.0.113.7", now=0.0)
    throttle.check_and_record("session-a:203.0.113.7", now=1.0)

    with pytest.raises(HTTPException) as exc_info:
        throttle.check_and_record("session-a:203.0.113.7", now=2.0)

    assert exc_info.value.status_code == 429
    throttle.check_and_record("session-b:203.0.113.7", now=2.0)
    throttle.check_and_record("session-c:203.0.113.7", now=2.0)
    assert len(throttle.attempts) == 2
