"""Normalized finding queries shared by the CTADMIN dashboard pages."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from eqm.models import Violation
from eqm.persistence import JsonStore
from eqm.projections import project_violation

TERMINAL_STATES = frozenset({"resolved", "rejected"})
SEVERITY_ORDER = ("critical", "high", "medium", "low")
TARGET_TYPE_ORDER = ("employee", "assignment", "entitlement", "resource")
WORKFLOW_BUCKETS = (
    ("not_started", "Not started", frozenset({"open"})),
    ("in_progress", "In progress", frozenset({"pending_approval", "approved", "manual_repair"})),
    ("complete", "Complete", TERMINAL_STATES),
)


def _normalise_set(values: frozenset[str]) -> frozenset[str]:
    return frozenset(str(value).strip().lower() for value in values if str(value).strip())


@dataclass(frozen=True, slots=True)
class FindingFilters:
    states: frozenset[str] = frozenset()
    severities: frozenset[str] = frozenset()
    target_types: frozenset[str] = frozenset()
    rules: frozenset[str] = frozenset()
    search: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "states", _normalise_set(self.states))
        object.__setattr__(self, "severities", _normalise_set(self.severities))
        object.__setattr__(self, "target_types", _normalise_set(self.target_types))
        object.__setattr__(self, "rules", _normalise_set(self.rules))
        object.__setattr__(self, "search", self.search.strip().casefold())


@dataclass(frozen=True, slots=True)
class DashboardKpis:
    total_findings: int
    critical_findings: int
    high_findings: int
    not_started_findings: int
    in_progress_findings: int
    complete_findings: int


@dataclass(frozen=True, slots=True)
class DashboardQueryResult:
    kpis: DashboardKpis
    series: dict[str, list[dict]]
    rows: list[dict]
    pagination: dict[str, int]
    entitlement_coverage: dict[str, int]
    catalog_findings: list[dict]


async def _read_list(store: JsonStore, name: str) -> list[dict]:
    data = await store.read(name)
    return data if isinstance(data, list) else []


def _row_keys(row: dict) -> tuple[str, str, str, str]:
    return (
        row["status"].lower().replace(" ", "_"),
        row["severity"].lower(),
        row["targetType"].lower(),
        row["ruleId"].lower(),
    )


def _matches(row: dict, filters: FindingFilters, *, ignore: str | None = None) -> bool:
    state, severity, target_type, rule = _row_keys(row)
    if ignore != "states" and filters.states and state not in filters.states:
        return False
    if ignore != "severities" and filters.severities and severity not in filters.severities:
        return False
    if ignore != "target_types" and filters.target_types and target_type not in filters.target_types:
        return False
    if ignore != "rules" and filters.rules and rule not in filters.rules:
        return False
    if not filters.states and ignore != "states" and state in TERMINAL_STATES:
        return False
    if filters.search:
        searchable = " ".join(
            str(row[key])
            for key in ("violationId", "userName", "ruleId", "ruleName", "reason", "targetType", "targetId")
        ).casefold()
        if filters.search not in searchable:
            return False
    return True


def _sort_rows(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (row["detectedAt"], row["violationId"]), reverse=True)


def _dimension_series(rows: list[dict], dimension: str) -> list[dict]:
    if dimension == "severity":
        counts = Counter(row["severity"].lower() for row in rows)
        return [
            {"key": value, "label": value.title(), "count": counts[value]}
            for value in SEVERITY_ORDER
            if counts[value]
        ]
    if dimension == "targetType":
        counts = Counter(row["targetType"].lower() for row in rows)
        return [
            {"key": value, "label": value.title(), "count": counts[value]}
            for value in TARGET_TYPE_ORDER
            if counts[value]
        ]
    if dimension == "rule":
        counts = Counter((row["ruleId"].lower(), row["ruleName"]) for row in rows)
        return [
            {"key": rule_id, "label": rule_name, "count": count}
            for (rule_id, rule_name), count in sorted(counts.items())
        ]
    if dimension == "workflow":
        states = Counter(row["status"].lower().replace(" ", "_") for row in rows)
        return [
            {"key": key, "label": label, "count": sum(states[state] for state in members)}
            for key, label, members in WORKFLOW_BUCKETS
        ]
    raise ValueError(f"Unknown dashboard dimension: {dimension}")


def _workflow_count(rows: list[dict], bucket: str) -> int:
    for key, _label, states in WORKFLOW_BUCKETS:
        if key == bucket:
            return sum(row["status"].lower().replace(" ", "_") in states for row in rows)
    raise ValueError(f"Unknown workflow bucket: {bucket}")


def _persona_rows(rows: list[dict], assignments: list[dict], persona_id: str | None) -> list[dict]:
    if persona_id is None:
        return rows
    active_assignments = [
        assignment
        for assignment in assignments
        if assignment.get("employee_id") == persona_id and assignment.get("active", True)
    ]
    assignment_ids = {assignment["id"] for assignment in active_assignments}
    entitlement_ids = {assignment["entitlement_id"] for assignment in active_assignments}
    return [
        row for row in rows
        if (row["targetType"] == "employee" and row["targetId"] == persona_id)
        or (row["targetType"] == "assignment" and row["targetId"] in assignment_ids)
        or (row["targetType"] == "entitlement" and row["targetId"] in entitlement_ids)
    ]


async def load_dashboard_query(
    store: JsonStore,
    filters: FindingFilters,
    persona_id: str | None = None,
) -> DashboardQueryResult:
    """Load one normalized row set and derive all dashboard outputs from it."""
    raw_vios, employees, assignments, entitlements, _resources = await _load_dashboard_data(store)
    emp_by_id = {employee["id"]: employee for employee in employees}
    asn_by_id = {assignment["id"]: assignment for assignment in assignments}
    projected = [
        project_violation(Violation(**raw), emp_by_id, asn_by_id)
        for raw in raw_vios
    ]
    scoped = _persona_rows(projected, assignments, persona_id)
    rows = _sort_rows([row for row in scoped if _matches(row, filters)])
    severity_rows = [row for row in scoped if _matches(row, filters, ignore="severities")]
    target_type_rows = [row for row in scoped if _matches(row, filters, ignore="target_types")]
    rule_rows = [row for row in scoped if _matches(row, filters, ignore="rules")]
    workflow_rows = [row for row in scoped if _matches(row, filters, ignore="states")]

    kpis = DashboardKpis(
        total_findings=len(rows),
        critical_findings=sum(row["severity"] == "Critical" for row in rows),
        high_findings=sum(row["severity"] == "High" for row in rows),
        not_started_findings=_workflow_count(rows, "not_started"),
        in_progress_findings=_workflow_count(rows, "in_progress"),
        complete_findings=_workflow_count(rows, "complete"),
    )
    catalog_findings = [row for row in rows if row["targetType"] == "entitlement"]
    finding_entitlement_ids = {row["targetId"] for row in catalog_findings}
    entitlement_ids = {entitlement["id"] for entitlement in entitlements}
    with_findings = len(entitlement_ids & finding_entitlement_ids)
    total = len(entitlement_ids)
    return DashboardQueryResult(
        kpis=kpis,
        series={
            "severity": _dimension_series(severity_rows, "severity"),
            "targetType": _dimension_series(target_type_rows, "targetType"),
            "rule": _dimension_series(rule_rows, "rule"),
            "workflow": _dimension_series(workflow_rows, "workflow"),
        },
        rows=rows,
        pagination={"page": 1, "pageSize": len(rows), "total": len(rows), "totalPages": 1 if rows else 0},
        entitlement_coverage={"total": total, "withFindings": with_findings, "withoutFindings": total - with_findings},
        catalog_findings=catalog_findings,
    )


async def _load_dashboard_data(store: JsonStore) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    return (
        await _read_list(store, "violations.json"),
        await _read_list(store, "hr_employees.json"),
        await _read_list(store, "assignments.json"),
        await _read_list(store, "entitlements.json"),
        await _read_list(store, "cmdb_resources.json"),
    )


async def load_personas(store: JsonStore) -> list[dict]:
    """Return active dashboard persona options without sensitive HR fields."""
    employees = await _read_list(store, "hr_employees.json")
    personas = [
        {
            "id": employee["id"],
            "fullName": employee["full_name"],
            "division": employee["current_division"],
            "role": employee["current_role"],
        }
        for employee in employees
        if employee.get("status") == "active"
    ]
    return sorted(personas, key=lambda persona: (persona["fullName"].casefold(), persona["id"]))
