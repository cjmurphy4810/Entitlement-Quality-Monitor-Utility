"""HTTP routes and shared rendering context for the CTADMIN surface."""

from __future__ import annotations

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
    validate_csrf,
)
from eqm.ctadmin.queries import FindingFilters, load_dashboard_query
from eqm.ctadmin.repairs import REPAIR_BUILDERS, RepairValidationError
from eqm.ctadmin.service import (
    RepairDidNotClearError,
    StaleFindingError,
    execute_repair,
)
from eqm.models import AccessTier, Violation, WorkflowState
from eqm.persistence import JsonStore
from eqm.projections import project_violation

CTADMIN_DIR = Path(__file__).parent
TEMPLATES_DIR = CTADMIN_DIR / "templates"
STATIC_DIR = CTADMIN_DIR / "static"

router = APIRouter(prefix="/ctadmin")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
login_throttle = LoginThrottle()
logger = logging.getLogger(__name__)

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


def _login_context(
    request: Request, *, next_path: str, error: str | None = None
) -> dict[str, object]:
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return principal


def _normalised_query_values(request: Request, name: str) -> list[str]:
    values: list[str] = []
    for raw_value in request.query_params.getlist(name):
        value = raw_value.strip().lower()
        if not value:
            continue
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
    request: Request,
    settings: Settings,
    principal: SessionPrincipal,
    *,
    include_terminal_default: bool = False,
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
    supported_rules = (
        {
            str(violation.get("rule_id", "")).strip().lower()
            for violation in raw_violations
            if isinstance(violation, dict)
        }
        if isinstance(raw_violations, list)
        else set()
    )
    if set(rules) - supported_rules:
        raise HTTPException(status_code=422, detail="Unsupported rule value")

    expanded_states: set[str] = set()
    for state_value in public_states:
        expanded_states.update(STATE_BUCKETS.get(state_value, frozenset({state_value})))
    if include_terminal_default and not public_states:
        expanded_states.update(RAW_STATES)
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


async def _read_records(store: JsonStore, name: str) -> list[dict]:
    raw = await store.read(name)
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


async def _finding_context(store: JsonStore, violation_id: str) -> dict[str, object] | None:
    violations = await _read_records(store, "violations.json")
    raw = next((item for item in violations if item.get("id") == violation_id), None)
    if raw is None:
        return None
    violation = Violation(**raw)
    employees = await _read_records(store, "hr_employees.json")
    assignments = await _read_records(store, "assignments.json")
    entitlements = await _read_records(store, "entitlements.json")
    resources = await _read_records(store, "cmdb_resources.json")
    employee_by_id = {item.get("id"): item for item in employees}
    assignment_by_id = {item.get("id"): item for item in assignments}
    entitlement_by_id = {item.get("id"): item for item in entitlements}
    resource_by_id = {item.get("id"): item for item in resources}
    target_sets = {
        "employee": employee_by_id,
        "assignment": assignment_by_id,
        "entitlement": entitlement_by_id,
        "resource": resource_by_id,
    }
    target = target_sets[violation.target_type].get(violation.target_id)
    related_employees: list[dict] = []
    if violation.target_type == "employee" and target:
        related_employees = [target]
    elif violation.target_type == "assignment" and target:
        employee = employee_by_id.get(target.get("employee_id"))
        related_employees = [employee] if employee else []
    elif violation.target_type == "entitlement":
        employee_ids = {
            item.get("employee_id")
            for item in assignments
            if item.get("entitlement_id") == violation.target_id and item.get("active", True)
        }
        related_employees = [
            employee_by_id[item_id] for item_id in sorted(employee_ids) if item_id in employee_by_id
        ]
    projection = project_violation(
        violation, employee_by_id, assignment_by_id, include_internal=True
    )
    return {
        "violation": violation,
        "finding": projection,
        "target": target,
        "related_employees": related_employees,
        "entitlements": entitlements,
        "assignments": assignments,
        "resources": resources,
    }


def _repair_preview_payload(context: dict[str, object]) -> dict[str, object]:
    violation = context["violation"]
    if not isinstance(violation, Violation):
        raise TypeError("Finding context is invalid")
    if violation.workflow_state in {WorkflowState.RESOLVED, WorkflowState.REJECTED}:
        raise StaleFindingError(
            f"Finding {violation.id} is already {violation.workflow_state.value}."
        )
    if violation.rule_id not in REPAIR_BUILDERS:
        raise RepairValidationError(f"No repair planner exists for rule {violation.rule_id}.")

    evidence = violation.evidence
    suggested = violation.suggested_fix
    fields: list[dict[str, object]]
    proposal: dict[str, object]
    kind: str
    if violation.rule_id in {"ENT-Q-01", "ENT-Q-02"}:
        kind = "pbl_textarea"
        initial = suggested.get("pbl_description") or evidence.get("pbl_description") or ""
        fields = [
            {
                "name": "pbl_description",
                "type": "textarea",
                "label": "New PBL description",
                "value": str(initial),
                "required": True,
            }
        ]
        proposal = {"pbl_description": str(initial)}
    elif violation.rule_id == "HR-03":
        kind = "acknowledgement"
        fields = [
            {
                "name": "manager_confirmed",
                "type": "checkbox",
                "label": "I confirm the manager approved revoking this legacy assignment.",
                "value": True,
                "required": True,
            }
        ]
        proposal = {"manager_confirmed": True}
    elif violation.rule_id == "CMDB-01":
        kind = "resource_select"
        resources = context.get("resources", [])
        options = [
            {"value": item["id"], "label": f"{item.get('name', item['id'])} · {item['id']}"}
            for item in resources
            if isinstance(item, dict) and item.get("id")
        ]
        fields = [
            {
                "name": "resource_id",
                "type": "select",
                "label": "CMDB resource",
                "options": options,
                "required": True,
            }
        ]
        proposal = {"resource_id": suggested.get("resource_id") or ""}
    elif violation.rule_id in {"TOX-01", "TOX-02"}:
        kind = "binary_side"
        if violation.rule_id == "TOX-01":
            pair = evidence.get("sod_pair")
            labels = (
                pair if isinstance(pair, list) and len(pair) == 2 else ["Left side", "Right side"]
            )
            options = [
                {"value": "left", "label": f"Revoke {labels[0]}"},
                {"value": "right", "label": f"Revoke {labels[1]}"},
            ]
        else:
            options = [
                {"value": "developer", "label": "Revoke developer-side assignments"},
                {"value": "operations", "label": "Revoke operations-side assignments"},
            ]
        fields = [
            {
                "name": "side",
                "type": "radio",
                "label": "Side to revoke",
                "options": options,
                "required": True,
            }
        ]
        proposal = {"side": ""}
    elif violation.rule_id == "TOX-03":
        kind = "assignment_multiselect"
        entitlements = {
            item.get("id"): item
            for item in context.get("entitlements", [])
            if isinstance(item, dict)
        }
        options = []
        for item in context.get("assignments", []):
            if not isinstance(item, dict) or not item.get("active", True):
                continue
            if item.get("employee_id") != violation.target_id:
                continue
            entitlement = entitlements.get(item.get("entitlement_id"))
            if entitlement and entitlement.get("access_tier") == int(AccessTier.ADMIN):
                options.append(
                    {
                        "value": item["id"],
                        "label": (
                            f"{item['id']} · {entitlement.get('name', item.get('entitlement_id'))} "
                            f"· {str(entitlement.get('division', '')).replace('_', ' ').title()}"
                        ),
                    }
                )
        fields = [
            {
                "name": "assignment_ids",
                "type": "multiselect",
                "label": "Tier-1 assignments to revoke",
                "options": options,
                "required": True,
            }
        ]
        proposal = {"assignment_ids": []}
    else:
        kind = "direct_change"
        if violation.rule_id in {"HR-01", "HR-02", "HR-04"}:
            proposal = {}
            description = f"Revoke assignment {violation.target_id}."
        elif violation.rule_id == "ENT-Q-03" or (
            violation.rule_id == "ENT-Q-04"
            and evidence.get("division") == "hr"
            and "developer" in evidence.get("acceptable_roles", [])
        ):
            forbidden = set(evidence.get("forbidden_roles", ["developer"]))
            roles = [role for role in evidence.get("acceptable_roles", []) if role not in forbidden]
            proposal = {"acceptable_roles": roles}
            description = f"Set acceptable roles to {roles}."
        else:
            proposal = {"access_tier": int(AccessTier.READ_WRITE)}
            description = "Set the entitlement access tier to Tier-2."
        fields = [
            {
                "name": "proposal",
                "type": "readonly",
                "label": "Verified direct change",
                "value": description,
            }
        ]

    return {
        "violationId": violation.id,
        "ruleId": violation.rule_id,
        "ruleName": violation.rule_name,
        "kind": kind,
        "reason": violation.explanation,
        "evidence": evidence,
        "suggestedFix": suggested,
        "fields": fields,
        "submission": proposal,
        "confirmLabel": "Confirm repair",
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
async def dashboard(request: Request, settings: Annotated[Settings, Depends(get_settings)]):
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
async def remediation(request: Request, settings: Annotated[Settings, Depends(get_settings)]):
    principal = _page_principal(request, settings)
    if isinstance(principal, RedirectResponse):
        return principal
    payload = await _dashboard_request(request, settings, principal, include_terminal_default=True)
    store = JsonStore(settings.data_dir)
    raw_violations = await _read_records(store, "violations.json")
    rule_options = sorted(
        {
            (str(item.get("rule_id", "")), str(item.get("rule_name", "")))
            for item in raw_violations
            if item.get("rule_id")
        }
    )
    origin = request.url.path
    if request.url.query:
        origin = f"{origin}?{request.url.query}"
    for row in payload["rows"]:
        if isinstance(row, dict):
            row["detailHref"] = (
                f"/ctadmin/findings/{quote(str(row['violationId']), safe='')}"
                f"?origin={quote(origin, safe='')}"
            )
            row["repairable"] = row.get("ruleId") in REPAIR_BUILDERS and row.get(
                "status", ""
            ).lower().replace(" ", "_") not in {"resolved", "rejected"}
    pagination = payload["pagination"]
    if isinstance(pagination, dict):
        current_page = int(pagination["page"])

        def page_href(page_number: int) -> str:
            pairs = [
                (key, value) for key, value in request.query_params.multi_items() if key != "page"
            ]
            pairs.append(("page", str(page_number)))
            return f"/ctadmin/remediation?{urlencode(pairs)}"

        pagination["previousHref"] = page_href(current_page - 1) if current_page > 1 else None
        pagination["nextHref"] = (
            page_href(current_page + 1) if current_page < int(pagination["totalPages"]) else None
        )
    return templates.TemplateResponse(
        request,
        "remediation.html",
        ctadmin_context(
            request,
            principal,
            page_title="Remediation",
            remediation_payload=payload,
            rule_options=rule_options,
            csrf_token=principal.csrf_token,
        ),
    )


@router.get("/findings/{violation_id}", response_class=HTMLResponse)
async def finding_detail(
    request: Request,
    violation_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    origin: str | None = None,
):
    principal = _page_principal(request, settings)
    if isinstance(principal, RedirectResponse):
        return principal
    context = await _finding_context(JsonStore(settings.data_dir), violation_id)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    violation = context["violation"]
    if not isinstance(violation, Violation):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    repairable = violation.rule_id in REPAIR_BUILDERS and violation.workflow_state not in {
        WorkflowState.RESOLVED,
        WorkflowState.REJECTED,
    }
    safe_origin = _safe_next(origin) if origin else "/ctadmin/remediation"
    return templates.TemplateResponse(
        request,
        "finding_detail.html",
        ctadmin_context(
            request,
            principal,
            page_title=f"Finding {violation.id}",
            **context,
            repairable=repairable,
            origin=safe_origin,
            csrf_token=principal.csrf_token,
        ),
    )


@router.get("/my-findings", response_class=HTMLResponse)
async def my_findings_placeholder(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
):
    return await _render_placeholder(
        request,
        settings,
        title="My Findings",
        heading="My findings",
        description="Persona-scoped findings will appear here.",
    )


@router.get("/api/dashboard")
async def dashboard_api(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, object]:
    principal = _api_principal(request, settings)
    return await _dashboard_request(request, settings, principal)


@router.get("/api/findings/{violation_id}/repair-preview")
@router.get("/api/findings/{violation_id}/repair-preview/", include_in_schema=False)
async def repair_preview(
    request: Request,
    violation_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    _api_principal(request, settings)
    context = await _finding_context(JsonStore(settings.data_dir), violation_id)
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    try:
        return _repair_preview_payload(context)
    except StaleFindingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RepairValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/actions/findings/{violation_id}/repair")
@router.post("/actions/findings/{violation_id}/repair/", include_in_schema=False)
async def repair_action(
    request: Request,
    violation_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    principal = _api_principal(request, settings)
    await validate_csrf(request, principal)
    try:
        submission = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(
            {"type": "validation_error", "detail": "Repair submission must be valid JSON."},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if not isinstance(submission, dict):
        return JSONResponse(
            {"type": "validation_error", "detail": "Repair submission must be an object."},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    try:
        receipt = await execute_repair(
            JsonStore(settings.data_dir), violation_id, principal.username, submission
        )
    except RepairValidationError as exc:
        return JSONResponse(
            {"type": "validation_error", "detail": str(exc)},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except StaleFindingError as exc:
        return JSONResponse(
            {"type": "stale_finding", "detail": str(exc)},
            status_code=status.HTTP_409_CONFLICT,
        )
    except RepairDidNotClearError as exc:
        return JSONResponse(
            {
                "type": "repair_did_not_clear",
                "detail": str(exc),
                "remaining": {
                    "reason": exc.violation.explanation,
                    "evidence": exc.violation.evidence,
                },
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    except Exception as exc:
        correlation_id = secrets.token_hex(8)
        logger.error(
            "CTADMIN repair failed type=%s correlation_id=%s",
            type(exc).__name__,
            correlation_id,
        )
        return JSONResponse(
            {"type": "server_error", "detail": "The repair could not be completed."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return JSONResponse(
        {
            "violationId": receipt.violation_id,
            "ruleId": receipt.rule_id,
            "targetType": receipt.target_type,
            "targetId": receipt.target_id,
            "cleared": receipt.cleared,
            "summary": receipt.summary,
            "choice": receipt.choice,
            "recordIds": list(receipt.record_ids),
            "changes": list(receipt.changes),
            "workflowState": receipt.workflow_state.value,
        }
    )


@router.api_route("/api", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def protected_api_root(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    _api_principal(request, settings)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="CTADMIN API resource not found"
    )


@router.api_route("/api/{resource:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def protected_api_placeholder(
    request: Request, resource: str, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    _api_principal(request, settings)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="CTADMIN API resource not found"
    )


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
