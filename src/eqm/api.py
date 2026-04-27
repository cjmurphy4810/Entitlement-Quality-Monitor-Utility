"""FastAPI app — skeleton with auth and health."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from eqm.config import Settings, get_settings
from eqm.dashboard import STATIC_DIR, TEMPLATES_DIR
from eqm.engine import run_engine
from eqm.models import (
    Assignment,
    CMDBResource,
    Entitlement,
    HREmployee,
    Violation,
    WorkflowHistoryEntry,
    WorkflowState,
)
from eqm.persistence import JsonStore
from eqm.rules.base import DataSnapshot
from eqm.scenarios import SCENARIOS, run_scenario
from eqm.seed import SeedBundle, SeedConfig, generate_seed
from eqm.simulator import drift_tick
from eqm.workflow import LEGAL_TRANSITIONS, IllegalTransition, transition

bearer_scheme = HTTPBearer(auto_error=False)
app = FastAPI(title="EQM Utility", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


ENTITLEMENT_PATCHABLE = {"name", "pbl_description", "access_tier",
                         "acceptable_roles", "division", "linked_resource_ids",
                         "sod_tags"}
EMPLOYEE_PATCHABLE = {"current_role", "current_division", "status", "manager_id",
                      "terminated_at"}
RESOURCE_PATCHABLE = {"name", "type", "criticality", "owner_division",
                      "environment", "linked_entitlement_ids", "description"}


async def _patch_record(store: JsonStore, name: str, item_id: str,
                        patch: dict, allowed: set[str], model) -> dict:
    raw = await _read_list(store, name)
    for i, x in enumerate(raw):
        if x.get("id") == item_id:
            unknown = set(patch) - allowed
            if unknown:
                raise HTTPException(400, f"Cannot patch fields: {sorted(unknown)}")
            x = {**x, **patch}
            if "updated_at" in model.model_fields:
                x["updated_at"] = datetime.now(UTC).isoformat()
            validated = model(**x).model_dump(mode="json")
            raw[i] = validated
            await store.write(name, raw)
            return validated
    raise HTTPException(404, "Not found")


@app.patch("/entitlements/{ent_id}", response_model=Entitlement,
           dependencies=[Depends(require_token)])
async def patch_entitlement(ent_id: str, patch: dict,
                            store: JsonStore = Depends(get_store)) -> Entitlement:  # noqa: B008
    return Entitlement(**await _patch_record(
        store, "entitlements.json", ent_id, patch,
        ENTITLEMENT_PATCHABLE, Entitlement))


@app.patch("/hr/employees/{emp_id}", response_model=HREmployee,
           dependencies=[Depends(require_token)])
async def patch_employee(emp_id: str, patch: dict,
                         store: JsonStore = Depends(get_store)) -> HREmployee:  # noqa: B008
    return HREmployee(**await _patch_record(
        store, "hr_employees.json", emp_id, patch,
        EMPLOYEE_PATCHABLE, HREmployee))


@app.patch("/cmdb/resources/{res_id}", response_model=CMDBResource,
           dependencies=[Depends(require_token)])
async def patch_resource(res_id: str, patch: dict,
                         store: JsonStore = Depends(get_store)) -> CMDBResource:  # noqa: B008
    return CMDBResource(**await _patch_record(
        store, "cmdb_resources.json", res_id, patch,
        RESOURCE_PATCHABLE, CMDBResource))


@app.delete("/assignments/{asn_id}", dependencies=[Depends(require_token)])
async def revoke_assignment(asn_id: str,
                            store: JsonStore = Depends(get_store)) -> dict:  # noqa: B008
    raw = await _read_list(store, "assignments.json")
    for i, x in enumerate(raw):
        if x.get("id") == asn_id:
            x["active"] = False
            raw[i] = x
            await store.write("assignments.json", raw)
            return {"id": asn_id, "active": False}
    raise HTTPException(404, "Assignment not found")


class TransitionRequest(BaseModel):
    to_state: WorkflowState
    actor: str
    note: str | None = None
    override_fix: dict | None = None


class ReopenRequest(BaseModel):
    actor: str
    note: str


@app.post("/violations/{vid}/transition", response_model=Violation,
          dependencies=[Depends(require_token)])
async def violation_transition(vid: str, body: TransitionRequest,
                               store: JsonStore = Depends(get_store)) -> Violation:  # noqa: B008
    raw = await _read_list(store, "violations.json")
    for i, x in enumerate(raw):
        if x.get("id") == vid:
            v = Violation(**x)
            try:
                transition(v, to=body.to_state, actor=body.actor,
                           note=body.note, override_fix=body.override_fix)
            except IllegalTransition as e:
                # Disambiguate: missing note vs disallowed transition.
                if (body.to_state in LEGAL_TRANSITIONS[v.workflow_state]
                    and body.to_state == WorkflowState.REJECTED
                    and not body.note):
                    raise HTTPException(400, "Rejection requires a note") from e
                raise HTTPException(409, str(e)) from e
            raw[i] = v.model_dump(mode="json")
            await store.write("violations.json", raw)
            return v
    raise HTTPException(404, "Violation not found")


@app.post("/violations/{vid}/reopen", response_model=Violation,
          dependencies=[Depends(require_token)])
async def violation_reopen(vid: str, body: ReopenRequest,
                            store: JsonStore = Depends(get_store)) -> Violation:  # noqa: B008
    raw = await _read_list(store, "violations.json")
    for i, x in enumerate(raw):
        if x.get("id") == vid:
            v = Violation(**x)
            if v.workflow_state != WorkflowState.REJECTED:
                raise HTTPException(409,
                    f"Reopen only valid from REJECTED; current={v.workflow_state.value}")
            v.workflow_history.append(WorkflowHistoryEntry(
                from_state=WorkflowState.REJECTED, to_state=WorkflowState.OPEN,
                actor=body.actor, timestamp=datetime.now(UTC),
                note=body.note,
            ))
            v.workflow_state = WorkflowState.OPEN
            raw[i] = v.model_dump(mode="json")
            await store.write("violations.json", raw)
            return v
    raise HTTPException(404, "Violation not found")


class ResetRequest(BaseModel):
    small: bool = False


class ScenarioRequest(BaseModel):
    name: str


async def _load_bundle(store: JsonStore) -> SeedBundle:
    return SeedBundle(
        entitlements=[Entitlement(**x) for x in await _read_list(store, "entitlements.json")],
        hr_employees=[HREmployee(**x) for x in await _read_list(store, "hr_employees.json")],
        cmdb_resources=[CMDBResource(**x) for x in await _read_list(store, "cmdb_resources.json")],
        assignments=[Assignment(**x) for x in await _read_list(store, "assignments.json")],
    )


async def _save_bundle_and_evaluate(store: JsonStore, bundle: SeedBundle) -> int:
    await store.write("entitlements.json",
                      [e.model_dump(mode="json") for e in bundle.entitlements])
    await store.write("hr_employees.json",
                      [e.model_dump(mode="json") for e in bundle.hr_employees])
    await store.write("cmdb_resources.json",
                      [e.model_dump(mode="json") for e in bundle.cmdb_resources])
    await store.write("assignments.json",
                      [e.model_dump(mode="json") for e in bundle.assignments])
    snap = DataSnapshot(bundle.entitlements, bundle.hr_employees,
                         bundle.cmdb_resources, bundle.assignments)
    existing_raw = await _read_list(store, "violations.json")
    existing = [Violation(**x) for x in existing_raw]
    result = run_engine(snap, existing_violations=existing)
    await store.write("violations.json",
                      [v.model_dump(mode="json") for v in result.violations])
    return result.new_count


@app.post("/simulate/reset", dependencies=[Depends(require_token)])
async def simulate_reset(body: ResetRequest,
                          store: JsonStore = Depends(get_store)) -> dict:  # noqa: B008
    cfg = (SeedConfig(num_entitlements=50, num_employees=100,
                      num_resources=15, num_assignments=200, seed=42)
           if body.small else SeedConfig())
    bundle = generate_seed(cfg)
    new_count = await _save_bundle_and_evaluate(store, bundle)
    return {"entitlements": len(bundle.entitlements),
            "hr_employees": len(bundle.hr_employees),
            "cmdb_resources": len(bundle.cmdb_resources),
            "assignments": len(bundle.assignments),
            "new_violations": new_count}


@app.post("/simulate/tick", dependencies=[Depends(require_token)])
async def simulate_tick(store: JsonStore = Depends(get_store)) -> dict:  # noqa: B008
    bundle = await _load_bundle(store)
    tick = int(datetime.now(UTC).timestamp()) // 60
    summary = drift_tick(bundle, tick_number=tick)
    new_count = await _save_bundle_and_evaluate(store, bundle)
    return {"tick_number": tick, "changes": summary.changes,
            "new_violations": new_count}


@app.post("/simulate/scenario", dependencies=[Depends(require_token)])
async def simulate_scenario(body: ScenarioRequest,
                             store: JsonStore = Depends(get_store)) -> dict:  # noqa: B008
    if body.name not in SCENARIOS:
        raise HTTPException(400, f"Unknown scenario. Known: {sorted(SCENARIOS)}")
    bundle = await _load_bundle(store)
    run_scenario(body.name, bundle)
    new_count = await _save_bundle_and_evaluate(store, bundle)
    return {"scenario": body.name, "new_violations": new_count}


@app.post("/sync/push-now", dependencies=[Depends(require_token)])
async def sync_push_now() -> dict:
    # Wired in Task 36 (git integration); for now return a stub.
    return {"status": "not_implemented_yet"}


@app.post("/sync/pull-now", dependencies=[Depends(require_token)])
async def sync_pull_now() -> dict:
    return {"status": "not_implemented_yet"}


def _scenarios_list() -> list[str]:
    return sorted(SCENARIOS.keys())


@app.get("/", response_class=HTMLResponse)
async def dashboard_overview(request: Request,
                              store: JsonStore = Depends(get_store)) -> HTMLResponse:  # noqa: B008
    ents = await _read_list(store, "entitlements.json")
    emps = await _read_list(store, "hr_employees.json")
    ress = await _read_list(store, "cmdb_resources.json")
    asns = await _read_list(store, "assignments.json")
    vios_raw = await _read_list(store, "violations.json")
    by_sev: dict[str, dict[str, int]] = defaultdict(
        lambda: {"open": 0, "pending_approval": 0, "resolved": 0})
    for v in vios_raw:
        sev = v.get("severity", "low")
        st = v.get("workflow_state", "open")
        bucket = by_sev[sev]
        if st in bucket:
            bucket[st] += 1
    return templates.TemplateResponse(request, "overview.html", {
        "counts": {"entitlements": len(ents), "hr_employees": len(emps),
                   "cmdb_resources": len(ress), "assignments": len(asns)},
        "violations_by": by_sev,
        "scenarios": _scenarios_list(),
    })


@app.post("/dashboard/actions/tick")
async def dashboard_action_tick(store: JsonStore = Depends(get_store)) -> RedirectResponse:  # noqa: B008
    bundle = await _load_bundle(store)
    tick = int(datetime.now(UTC).timestamp()) // 60
    drift_tick(bundle, tick_number=tick)
    await _save_bundle_and_evaluate(store, bundle)
    return RedirectResponse("/", status_code=303)


@app.post("/dashboard/actions/scenario")
async def dashboard_action_scenario(name: Annotated[str, Form()],
                                      store: JsonStore = Depends(get_store)) -> RedirectResponse:  # noqa: B008
    if name not in SCENARIOS:
        raise HTTPException(400, "Unknown scenario")
    bundle = await _load_bundle(store)
    run_scenario(name, bundle)
    await _save_bundle_and_evaluate(store, bundle)
    return RedirectResponse("/", status_code=303)


@app.post("/dashboard/actions/reset")
async def dashboard_action_reset(store: JsonStore = Depends(get_store)) -> RedirectResponse:  # noqa: B008
    bundle = generate_seed(SeedConfig(num_entitlements=50, num_employees=100,
                                        num_resources=15, num_assignments=200, seed=42))
    await _save_bundle_and_evaluate(store, bundle)
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard/entitlements", response_class=HTMLResponse)
async def dashboard_entitlements(request: Request,
                                   store: JsonStore = Depends(get_store)) -> HTMLResponse:  # noqa: B008
    items = await _read_list(store, "entitlements.json")
    return templates.TemplateResponse(request, "entitlements.html",
                                       {"items": items, "scenarios": _scenarios_list()})


@app.get("/dashboard/hr", response_class=HTMLResponse)
async def dashboard_hr(request: Request,
                        store: JsonStore = Depends(get_store)) -> HTMLResponse:  # noqa: B008
    items = await _read_list(store, "hr_employees.json")
    return templates.TemplateResponse(request, "hr.html",
                                       {"items": items, "scenarios": _scenarios_list()})


@app.get("/dashboard/cmdb", response_class=HTMLResponse)
async def dashboard_cmdb(request: Request,
                          store: JsonStore = Depends(get_store)) -> HTMLResponse:  # noqa: B008
    items = await _read_list(store, "cmdb_resources.json")
    return templates.TemplateResponse(request, "cmdb.html",
                                       {"items": items, "scenarios": _scenarios_list()})


@app.get("/dashboard/violations", response_class=HTMLResponse)
async def dashboard_violations(request: Request,
                                 store: JsonStore = Depends(get_store)) -> HTMLResponse:  # noqa: B008
    items = await _read_list(store, "violations.json")
    return templates.TemplateResponse(request, "violations.html",
                                       {"items": items, "scenarios": _scenarios_list()})
