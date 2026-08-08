"""Normalized finding queries shared by the CTADMIN dashboard pages."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from eqm.models import Violation
from eqm.persistence import JsonStore
from eqm.projections import project_violation

DEFAULT_PAGE_SIZE = 50
TERMINAL_STATES = frozenset({"resolved", "rejected"})
SEVERITY_ORDER = ("critical", "high", "medium", "low")
TARGET_TYPE_ORDER = ("employee", "assignment", "entitlement", "resource")
WORKFLOW_BUCKETS = (
    ("not_started", "Not started", frozenset({"open"})),
    ("in_progress", "In progress", frozenset({"pending_approval", "approved", "manual_repair"})),
    ("complete", "Complete", TERMINAL_STATES),
)
ASSIGNMENT_STATUS_ORDER = (
    ("clean", "Clean"),
    ("open", "Open"),
    ("pending_approval", "Pending Approval"),
    ("approved", "Approved"),
    ("manual_repair", "Manual Repair"),
)
ASSIGNMENT_STATUS_PRIORITY = {
    key: priority for priority, (key, _label) in enumerate(ASSIGNMENT_STATUS_ORDER)
}


def _normalise_set(values: frozenset[str]) -> frozenset[str]:
    return frozenset(str(value).strip().lower() for value in values if str(value).strip())


def _normalise_positive(value: int, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class FindingFilters:
    states: frozenset[str] = frozenset()
    severities: frozenset[str] = frozenset()
    target_types: frozenset[str] = frozenset()
    rules: frozenset[str] = frozenset()
    assignment_statuses: frozenset[str] = frozenset()
    coverage: frozenset[str] = frozenset()
    search: str = ""
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        object.__setattr__(self, "states", _normalise_set(self.states))
        object.__setattr__(self, "severities", _normalise_set(self.severities))
        object.__setattr__(self, "target_types", _normalise_set(self.target_types))
        object.__setattr__(self, "rules", _normalise_set(self.rules))
        object.__setattr__(self, "assignment_statuses", _normalise_set(self.assignment_statuses))
        object.__setattr__(self, "coverage", _normalise_set(self.coverage))
        object.__setattr__(self, "search", self.search.strip().casefold())
        object.__setattr__(self, "page", _normalise_positive(self.page, 1))
        object.__setattr__(
            self, "page_size", _normalise_positive(self.page_size, DEFAULT_PAGE_SIZE)
        )


@dataclass(frozen=True, slots=True)
class DashboardKpis:
    total_assignments: int
    total_findings: int
    high_critical_findings: int
    catalog_findings: int
    critical_findings: int
    high_findings: int
    not_started_findings: int
    in_progress_findings: int
    complete_findings: int
    open_findings: int
    pending_approval_findings: int
    resolved_findings: int


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


def _matches(
    row: dict,
    filters: FindingFilters,
    *,
    row_assignment_ids: dict[str, frozenset[str]],
    row_entitlement_ids: dict[str, frozenset[str]],
    assignment_statuses: dict[str, str],
    affected_entitlement_ids: frozenset[str],
    ignore: str | None = None,
) -> bool:
    state, severity, target_type, rule = _row_keys(row)
    if ignore != "states" and filters.states and state not in filters.states:
        return False
    if ignore != "severities" and filters.severities and severity not in filters.severities:
        return False
    if (
        ignore != "target_types"
        and filters.target_types
        and target_type not in filters.target_types
    ):
        return False
    if ignore != "rules" and filters.rules and rule not in filters.rules:
        return False
    if ignore != "assignment_statuses" and filters.assignment_statuses:
        selected_assignments = {
            assignment_id
            for assignment_id, assignment_status in assignment_statuses.items()
            if assignment_status in filters.assignment_statuses
        }
        if not row_assignment_ids[row["violationId"]] & selected_assignments:
            return False
    if ignore != "coverage" and filters.coverage:
        affects_covered_entitlement = bool(
            row_entitlement_ids[row["violationId"]] & affected_entitlement_ids
        )
        if "with_findings" not in filters.coverage or not affects_covered_entitlement:
            return False
    if not filters.states and ignore != "states" and state in TERMINAL_STATES:
        return False
    if filters.search:
        searchable = " ".join(
            str(row[key])
            for key in (
                "violationId",
                "userName",
                "ruleId",
                "ruleName",
                "reason",
                "targetType",
                "targetId",
            )
        ).casefold()
        if filters.search not in searchable:
            return False
    return True


def _relationships_by_row(
    rows: list[dict],
    assignments: list[dict],
    entitlements: list[dict],
    resources: list[dict],
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    assignment_by_id = {str(item["id"]): item for item in assignments}
    entitlement_ids = {str(item["id"]) for item in entitlements}
    active_by_employee: dict[str, set[str]] = {}
    active_by_entitlement: dict[str, set[str]] = {}
    for assignment in assignments:
        if not assignment.get("active", True):
            continue
        assignment_id = str(assignment["id"])
        active_by_employee.setdefault(str(assignment["employee_id"]), set()).add(assignment_id)
        active_by_entitlement.setdefault(str(assignment["entitlement_id"]), set()).add(
            assignment_id
        )

    entitlements_by_resource: dict[str, set[str]] = {}
    for entitlement in entitlements:
        entitlement_id = str(entitlement["id"])
        for resource_id in entitlement.get("linked_resource_ids", []):
            entitlements_by_resource.setdefault(str(resource_id), set()).add(entitlement_id)
    for resource in resources:
        resource_id = str(resource["id"])
        for entitlement_id in resource.get("linked_entitlement_ids", []):
            normalized_id = str(entitlement_id)
            if normalized_id in entitlement_ids:
                entitlements_by_resource.setdefault(resource_id, set()).add(normalized_id)

    row_assignment_ids: dict[str, frozenset[str]] = {}
    row_entitlement_ids: dict[str, frozenset[str]] = {}
    for row in rows:
        target_type = row["targetType"]
        target_id = row["targetId"]
        related_assignments: set[str]
        related_entitlements: set[str]
        if target_type == "assignment":
            assignment = assignment_by_id.get(target_id)
            related_assignments = {target_id} if assignment is not None else set()
            related_entitlements = (
                {str(assignment["entitlement_id"])} if assignment is not None else set()
            )
        elif target_type == "employee":
            related_assignments = set(active_by_employee.get(target_id, set()))
            related_entitlements = {
                str(assignment_by_id[assignment_id]["entitlement_id"])
                for assignment_id in related_assignments
            }
        elif target_type == "entitlement":
            related_entitlements = {target_id} if target_id in entitlement_ids else set()
            related_assignments = set(active_by_entitlement.get(target_id, set()))
        elif target_type == "resource":
            related_entitlements = set(entitlements_by_resource.get(target_id, set()))
            related_assignments = set().union(
                *(active_by_entitlement.get(entitlement_id, set()) for entitlement_id in related_entitlements)
            )
        else:
            related_assignments = set()
            related_entitlements = set()
        row_assignment_ids[row["violationId"]] = frozenset(related_assignments)
        row_entitlement_ids[row["violationId"]] = frozenset(related_entitlements)
    return row_assignment_ids, row_entitlement_ids


def _assignment_status_map(
    assignments: list[dict],
    rows: list[dict],
    row_assignment_ids: dict[str, frozenset[str]],
) -> dict[str, str]:
    status_by_assignment = {str(assignment["id"]): "clean" for assignment in assignments}
    for row in rows:
        state = row["status"].lower().replace(" ", "_")
        if state not in ASSIGNMENT_STATUS_PRIORITY:
            continue
        for assignment_id in row_assignment_ids[row["violationId"]]:
            current = status_by_assignment[assignment_id]
            if ASSIGNMENT_STATUS_PRIORITY[state] > ASSIGNMENT_STATUS_PRIORITY[current]:
                status_by_assignment[assignment_id] = state
    return status_by_assignment


def _assignment_status_series(statuses: dict[str, str]) -> list[dict]:
    counts = Counter(statuses.values())
    return [
        {"key": key, "label": label, "count": counts[key]}
        for key, label in ASSIGNMENT_STATUS_ORDER
        if key in {"clean", "open", "pending_approval"} or counts[key]
    ]


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
        row
        for row in rows
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
    raw_vios, employees, assignments, entitlements, resources = await _load_dashboard_data(store)
    emp_by_id = {employee["id"]: employee for employee in employees}
    asn_by_id = {assignment["id"]: assignment for assignment in assignments}
    projected = [project_violation(Violation(**raw), emp_by_id, asn_by_id) for raw in raw_vios]
    scoped = _persona_rows(projected, assignments, persona_id)
    row_assignment_ids, row_entitlement_ids = _relationships_by_row(
        scoped, assignments, entitlements, resources
    )
    active_scoped = [
        row
        for row in scoped
        if row["status"].lower().replace(" ", "_") not in TERMINAL_STATES
    ]
    global_assignment_statuses = _assignment_status_map(
        assignments, active_scoped, row_assignment_ids
    )
    affected_entitlement_ids = frozenset(
        entitlement_id
        for row in active_scoped
        for entitlement_id in row_entitlement_ids[row["violationId"]]
    )

    def matches(row: dict, ignore: str | None = None) -> bool:
        return _matches(
            row,
            filters,
            row_assignment_ids=row_assignment_ids,
            row_entitlement_ids=row_entitlement_ids,
            assignment_statuses=global_assignment_statuses,
            affected_entitlement_ids=affected_entitlement_ids,
            ignore=ignore,
        )

    filtered_rows = _sort_rows([row for row in scoped if matches(row)])
    severity_rows = [row for row in scoped if matches(row, "severities")]
    target_type_rows = [row for row in scoped if matches(row, "target_types")]
    rule_rows = [row for row in scoped if matches(row, "rules")]
    workflow_rows = [row for row in scoped if matches(row, "states")]
    assignment_status_rows = [row for row in scoped if matches(row, "assignment_statuses")]
    assignment_statuses = _assignment_status_map(
        assignments, assignment_status_rows, row_assignment_ids
    )
    coverage_rows = [row for row in scoped if matches(row, "coverage")]
    total = len(filtered_rows)
    start = (filters.page - 1) * filters.page_size
    rows = filtered_rows[start : start + filters.page_size]

    kpis = DashboardKpis(
        total_assignments=(
            sum(
                assignment_status in filters.assignment_statuses
                for assignment_status in assignment_statuses.values()
            )
            if filters.assignment_statuses
            else len(assignments)
        ),
        total_findings=total,
        high_critical_findings=sum(
            row["severity"] in {"Critical", "High"} for row in filtered_rows
        ),
        catalog_findings=sum(row["targetType"] == "entitlement" for row in filtered_rows),
        critical_findings=sum(row["severity"] == "Critical" for row in filtered_rows),
        high_findings=sum(row["severity"] == "High" for row in filtered_rows),
        not_started_findings=_workflow_count(filtered_rows, "not_started"),
        in_progress_findings=_workflow_count(filtered_rows, "in_progress"),
        complete_findings=_workflow_count(filtered_rows, "complete"),
        open_findings=sum(row["status"] == "Open" for row in filtered_rows),
        pending_approval_findings=sum(row["status"] == "Pending Approval" for row in filtered_rows),
        resolved_findings=sum(row["status"] == "Resolved" for row in filtered_rows),
    )
    catalog_findings = [row for row in filtered_rows if row["targetType"] == "entitlement"]
    finding_entitlement_ids = {
        entitlement_id
        for row in coverage_rows
        if row["status"].lower().replace(" ", "_") not in TERMINAL_STATES
        for entitlement_id in row_entitlement_ids[row["violationId"]]
    }
    entitlement_ids = {entitlement["id"] for entitlement in entitlements}
    with_findings = len(entitlement_ids & finding_entitlement_ids)
    entitlement_total = len(entitlement_ids)
    return DashboardQueryResult(
        kpis=kpis,
        series={
            "severity": _dimension_series(severity_rows, "severity"),
            "targetType": _dimension_series(target_type_rows, "targetType"),
            "rule": _dimension_series(rule_rows, "rule"),
            "workflow": _dimension_series(workflow_rows, "workflow"),
            "assignmentStatus": _assignment_status_series(assignment_statuses),
        },
        rows=rows,
        pagination={
            "page": filters.page,
            "pageSize": filters.page_size,
            "total": total,
            "totalPages": (total + filters.page_size - 1) // filters.page_size,
        },
        entitlement_coverage={
            "total": entitlement_total,
            "withFindings": with_findings,
            "withoutFindings": entitlement_total - with_findings,
        },
        catalog_findings=catalog_findings,
    )


async def _load_dashboard_data(
    store: JsonStore,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
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
