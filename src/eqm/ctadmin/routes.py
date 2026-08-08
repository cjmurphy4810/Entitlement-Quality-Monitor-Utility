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
from eqm.ctadmin.queries import FindingFilters, load_dashboard_query
from eqm.persistence import JsonStore

CTADMIN_DIR = Path(__file__).parent
TEMPLATES_DIR = CTADMIN_DIR / "templates"
STATIC_DIR = CTADMIN_DIR / "static"

router = APIRouter(prefix="/ctadmin")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
login_throttle = LoginThrottle()

STATE_BUCKETS = {
    "not_started": frozenset({"open"}),
    "in_progress": frozenset({"pending_approval", "approved", "manual_repair"}),
    "complete": frozenset({"resolved", "rejected"}),
}
RAW_STATES = frozenset().union(*STATE_BUCKETS.values())
SEVERITIES = frozenset({"critical", "high", "medium", "low"})
TARGET_TYPES = frozenset({"employee", "assignment", "entitlement", "resource"})


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


def _normalised_query_values(request: Request, name: str) -> list[str]:
    values: list[str] = []
    for raw_value in request.query_params.getlist(name):
        value = raw_value.strip().lower()
        if not value:
            raise HTTPException(status_code=422, detail=f"Unsupported {name} value")
        if value not in values:
            values.append(value)
    return values


def _positive_query_int(request: Request, name: str, default: int) -> int:
    raw_value = request.query_params.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be a positive integer") from exc
    if value < 1 or (name == "pageSize" and value > 200):
        raise HTTPException(status_code=422, detail=f"{name} must be a positive integer")
    return value


async def _dashboard_request(
    request: Request, settings: Settings, principal: SessionPrincipal
) -> dict[str, object]:
    public_states = _normalised_query_values(request, "state")
    severities = _normalised_query_values(request, "severity")
    target_types = _normalised_query_values(request, "targetType")
    rules = _normalised_query_values(request, "rule")
    search = request.query_params.get("search", "").strip()
    page = _positive_query_int(request, "page", 1)
    page_size = _positive_query_int(request, "pageSize", 50)

    unsupported_states = set(public_states) - (set(STATE_BUCKETS) | set(RAW_STATES))
    unsupported_severities = set(severities) - set(SEVERITIES)
    unsupported_targets = set(target_types) - set(TARGET_TYPES)
    if unsupported_states:
        raise HTTPException(status_code=422, detail="Unsupported state value")
    if unsupported_severities:
        raise HTTPException(status_code=422, detail="Unsupported severity value")
    if unsupported_targets:
        raise HTTPException(status_code=422, detail="Unsupported targetType value")

    store = JsonStore(settings.data_dir)
    raw_violations = await store.read("violations.json")
    supported_rules = {
        str(violation.get("rule_id", "")).strip().lower()
        for violation in raw_violations if isinstance(violation, dict)
    } if isinstance(raw_violations, list) else set()
    if set(rules) - supported_rules:
        raise HTTPException(status_code=422, detail="Unsupported rule value")

    expanded_states: set[str] = set()
    for state_value in public_states:
        expanded_states.update(STATE_BUCKETS.get(state_value, frozenset({state_value})))
    query_result = await load_dashboard_query(
        store,
        FindingFilters(
            states=frozenset(expanded_states),
            severities=frozenset(severities),
            target_types=frozenset(target_types),
            rules=frozenset(rules),
            search=search,
            page=page,
            page_size=page_size,
        ),
        persona_id=None if principal.persona_id == "ctadmin" else principal.persona_id,
    )
    kpis = query_result.kpis
    return {
        "kpis": {
            "totalFindings": kpis.total_findings,
            "criticalFindings": kpis.critical_findings,
            "highFindings": kpis.high_findings,
            "notStartedFindings": kpis.not_started_findings,
            "inProgressFindings": kpis.in_progress_findings,
            "completeFindings": kpis.complete_findings,
        },
        "coverage": query_result.entitlement_coverage,
        "series": {
            "status": query_result.series["workflow"],
            "severity": query_result.series["severity"],
            "targetType": query_result.series["targetType"],
            "rule": query_result.series["rule"],
        },
        "rows": query_result.rows,
        "filters": {
            "state": public_states,
            "severity": severities,
            "targetType": target_types,
            "rule": rules,
            "search": search,
            "page": page,
            "pageSize": page_size,
        },
        "pagination": query_result.pagination,
    }


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
async def dashboard(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
):
    principal = _page_principal(request, settings)
    if isinstance(principal, RedirectResponse):
        return principal
    payload = await _dashboard_request(request, settings, principal)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        ctadmin_context(
            request,
            principal,
            page_title="Health dashboard",
            dashboard_payload=payload,
        ),
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


@router.get("/api/dashboard")
async def dashboard_api(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, object]:
    principal = _api_principal(request, settings)
    return await _dashboard_request(request, settings, principal)


@router.api_route("/api", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def protected_api_root(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    _api_principal(request, settings)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CTADMIN API resource not found")


@router.api_route("/api/{resource:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def protected_api_placeholder(
    request: Request, resource: str, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    _api_principal(request, settings)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CTADMIN API resource not found")


@router.api_route("/actions", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def protected_action_root(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    _api_principal(request, settings)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CTADMIN action not found")


@router.api_route("/actions/{resource:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def protected_action_placeholder(
    request: Request, resource: str, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    _api_principal(request, settings)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CTADMIN action not found")
