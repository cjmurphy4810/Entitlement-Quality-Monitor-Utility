"""HTTP routes and shared rendering context for the CTADMIN surface."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from eqm.config import Settings, get_settings
from eqm.ctadmin.auth import (
    SESSION_COOKIE_NAME,
    LoginThrottle,
    SessionCodec,
    SessionPrincipal,
    get_principal,
    login_throttle_key,
    validate_credentials,
)

CTADMIN_DIR = Path(__file__).parent
TEMPLATES_DIR = CTADMIN_DIR / "templates"
STATIC_DIR = CTADMIN_DIR / "static"

router = APIRouter(prefix="/ctadmin")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
login_throttle = LoginThrottle()


def ctadmin_context(
    request: Request, principal: SessionPrincipal, **values: object
) -> dict[str, object]:
    """Provide the shared template values for an authenticated CTADMIN page."""
    return {
        "request": request,
        "principal": principal,
        "username": principal.username,
        "persona_id": principal.persona_id,
        **values,
    }


def _safe_next(next_path: str | None) -> str:
    """Return a CTADMIN-local return path, defaulting to the dashboard."""
    if not next_path or not next_path.startswith("/ctadmin/") or next_path.startswith("//"):
        return "/ctadmin/dashboard"
    parsed = urlsplit(next_path)
    if parsed.scheme or parsed.netloc:
        return "/ctadmin/dashboard"
    return next_path


def _login_context(request: Request, *, next_path: str, error: str | None = None) -> dict[str, object]:
    return {"request": request, "next_path": next_path, "error": error}


def _page_login_redirect(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(
        f"/ctadmin/login?{urlencode({'next': next_path})}", status_code=status.HTTP_303_SEE_OTHER
    )


def _page_principal(request: Request, settings: Settings) -> SessionPrincipal | RedirectResponse:
    principal = get_principal(request, settings)
    return principal if principal is not None else _page_login_redirect(request)


def _api_principal(request: Request, settings: Settings) -> SessionPrincipal:
    principal = get_principal(request, settings)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return principal


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "login.html", _login_context(request, next_path=_safe_next(next))
    )


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    settings: Annotated[Settings, Depends(get_settings)],
    next: Annotated[str | None, Form()] = None,
):
    safe_next = _safe_next(next)
    throttle_key = login_throttle_key(username, request)
    login_throttle.check(throttle_key, now=time.time())
    if not validate_credentials(username, password, settings):
        login_throttle.record_failure(throttle_key, now=time.time())
        return templates.TemplateResponse(
            request,
            "login.html",
            _login_context(request, next_path=safe_next, error="Invalid username or password"),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    login_throttle.clear(throttle_key)
    token = SessionCodec(
        settings.ctadmin_session_secret.get_secret_value(), settings.ctadmin_session_ttl_seconds
    ).encode(username)
    response = RedirectResponse(safe_next, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.ctadmin_session_ttl_seconds,
        httponly=True,
        secure=settings.ctadmin_secure_cookies,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/ctadmin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


async def _render_placeholder(
    request: Request, settings: Settings, *, title: str, heading: str, description: str
) -> HTMLResponse | RedirectResponse:
    principal = _page_principal(request, settings)
    if isinstance(principal, RedirectResponse):
        return principal
    return templates.TemplateResponse(
        request,
        "base.html",
        ctadmin_context(
            request,
            principal,
            page_title=title,
            page_heading=heading,
            page_description=description,
        ),
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_placeholder(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
):
    return await _render_placeholder(
        request, settings, title="Dashboard", heading="Health dashboard",
        description="A verified view of entitlement quality is loading.",
    )


@router.get("/remediation", response_class=HTMLResponse)
async def remediation_placeholder(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
):
    return await _render_placeholder(
        request, settings, title="Remediation", heading="Remediation queue",
        description="Prioritized repair paths will appear here.",
    )


@router.get("/findings/{violation_id}", response_class=HTMLResponse)
async def finding_placeholder(
    request: Request, violation_id: str, settings: Annotated[Settings, Depends(get_settings)]
):
    return await _render_placeholder(
        request, settings, title="Finding detail", heading=f"Finding {violation_id}",
        description="Evidence and a verified repair path will appear here.",
    )


@router.get("/my-findings", response_class=HTMLResponse)
async def my_findings_placeholder(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
):
    return await _render_placeholder(
        request, settings, title="My Findings", heading="My findings",
        description="Persona-scoped findings will appear here.",
    )


@router.api_route("/api/{resource:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def protected_api_placeholder(
    request: Request, resource: str, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    _api_principal(request, settings)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CTADMIN API resource not found")


@router.api_route("/actions/{resource:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def protected_action_placeholder(
    request: Request, resource: str, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    _api_principal(request, settings)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CTADMIN action not found")
