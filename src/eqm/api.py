"""FastAPI app — skeleton with auth and health."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from eqm.config import Settings, get_settings
from eqm.models import (
    Assignment,
    CMDBResource,
    Entitlement,
    HREmployee,
    Violation,
)
from eqm.persistence import JsonStore

bearer_scheme = HTTPBearer(auto_error=False)
app = FastAPI(title="EQM Utility", version="0.1.0")


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    if credentials is None or credentials.credentials != settings.bearer_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing or invalid bearer token")


def get_store(settings: Settings = Depends(get_settings)) -> JsonStore:  # noqa: B008
    return JsonStore(settings.data_dir)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/simulate/tick", dependencies=[Depends(require_token)])
def simulate_tick_placeholder() -> dict:
    return {"todo": "wired in Task 32"}


async def _read_list(store: JsonStore, name: str) -> list[dict]:
    data = await store.read(name)
    return data if isinstance(data, list) else []


@app.get("/entitlements", response_model=list[Entitlement])
async def get_entitlements(
    division: str | None = None,
    tier: int | None = Query(None, ge=1, le=4),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = 0,
    store: JsonStore = Depends(get_store),  # noqa: B008
) -> list[Entitlement]:
    raw = await _read_list(store, "entitlements.json")
    items = [Entitlement(**x) for x in raw]
    if division:
        items = [e for e in items if e.division.value == division]
    if tier:
        items = [e for e in items if int(e.access_tier) == tier]
    return items[offset:offset + limit]


@app.get("/entitlements/{ent_id}", response_model=Entitlement)
async def get_entitlement(ent_id: str, store: JsonStore = Depends(get_store)) -> Entitlement:  # noqa: B008
    raw = await _read_list(store, "entitlements.json")
    for x in raw:
        if x.get("id") == ent_id:
            return Entitlement(**x)
    raise HTTPException(404, "Entitlement not found")


@app.get("/hr/employees", response_model=list[HREmployee])
async def get_employees(
    division: str | None = None,
    role: str | None = None,
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = 0,
    store: JsonStore = Depends(get_store),  # noqa: B008
) -> list[HREmployee]:
    raw = await _read_list(store, "hr_employees.json")
    items = [HREmployee(**x) for x in raw]
    if division:
        items = [e for e in items if e.current_division.value == division]
    if role:
        items = [e for e in items if e.current_role.value == role]
    return items[offset:offset + limit]


@app.get("/hr/employees/{emp_id}", response_model=HREmployee)
async def get_employee(emp_id: str, store: JsonStore = Depends(get_store)) -> HREmployee:  # noqa: B008
    raw = await _read_list(store, "hr_employees.json")
    for x in raw:
        if x.get("id") == emp_id:
            return HREmployee(**x)
    raise HTTPException(404, "Employee not found")


@app.get("/cmdb/resources", response_model=list[CMDBResource])
async def get_resources(
    criticality: str | None = None,
    environment: str | None = None,
    store: JsonStore = Depends(get_store),  # noqa: B008
) -> list[CMDBResource]:
    raw = await _read_list(store, "cmdb_resources.json")
    items = [CMDBResource(**x) for x in raw]
    if criticality:
        items = [r for r in items if r.criticality.value == criticality]
    if environment:
        items = [r for r in items if r.environment == environment]
    return items


@app.get("/cmdb/resources/{res_id}", response_model=CMDBResource)
async def get_resource(res_id: str, store: JsonStore = Depends(get_store)) -> CMDBResource:  # noqa: B008
    raw = await _read_list(store, "cmdb_resources.json")
    for x in raw:
        if x.get("id") == res_id:
            return CMDBResource(**x)
    raise HTTPException(404, "Resource not found")


@app.get("/assignments", response_model=list[Assignment])
async def get_assignments(
    employee_id: str | None = None,
    entitlement_id: str | None = None,
    active: bool | None = None,
    store: JsonStore = Depends(get_store),  # noqa: B008
) -> list[Assignment]:
    raw = await _read_list(store, "assignments.json")
    items = [Assignment(**x) for x in raw]
    if employee_id:
        items = [a for a in items if a.employee_id == employee_id]
    if entitlement_id:
        items = [a for a in items if a.entitlement_id == entitlement_id]
    if active is not None:
        items = [a for a in items if a.active == active]
    return items


@app.get("/violations", response_model=list[Violation])
async def get_violations(
    state: str | None = None,
    severity: str | None = None,
    since: str | None = None,
    store: JsonStore = Depends(get_store),  # noqa: B008
) -> list[Violation]:
    raw = await _read_list(store, "violations.json")
    items = [Violation(**x) for x in raw]
    if state:
        items = [v for v in items if v.workflow_state.value == state]
    if severity:
        items = [v for v in items if v.severity.value == severity]
    if since:
        from datetime import datetime
        cutoff = datetime.fromisoformat(since)
        items = [v for v in items if v.detected_at >= cutoff]
    return items


@app.get("/violations/{vid}", response_model=Violation)
async def get_violation(vid: str, store: JsonStore = Depends(get_store)) -> Violation:  # noqa: B008
    raw = await _read_list(store, "violations.json")
    for x in raw:
        if x.get("id") == vid:
            return Violation(**x)
    raise HTTPException(404, "Violation not found")
