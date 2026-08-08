import json

import pytest

from eqm.ctadmin.queries import FindingFilters, load_dashboard_query, load_personas
from eqm.persistence import JsonStore


def _write_fixture(tmp_path):
    """Five JSON lists covering every dashboard dimension and join path."""
    files = {
        "hr_employees.json": [
            {"id": "EMP-1", "full_name": "Ada Lovelace", "email": "ada@example.com",
             "current_role": "operations", "current_division": "tech_ops", "status": "active",
             "role_history": [], "manager_id": None, "hired_at": "2024-01-01T00:00:00+00:00",
             "terminated_at": None},
            {"id": "EMP-2", "full_name": "Grace Hopper", "email": "grace@example.com",
             "current_role": "developer", "current_division": "tech_dev", "status": "active",
             "role_history": [], "manager_id": None, "hired_at": "2024-01-01T00:00:00+00:00",
             "terminated_at": None},
            {"id": "EMP-3", "full_name": "Retired User", "email": "retired@example.com",
             "current_role": "operations", "current_division": "tech_ops", "status": "terminated",
             "role_history": [], "manager_id": None, "hired_at": "2024-01-01T00:00:00+00:00",
             "terminated_at": "2025-01-01T00:00:00+00:00"},
        ],
        "entitlements.json": [
            {"id": "ENT-1", "name": "Database Admin", "pbl_description": "Database administration access.",
             "access_tier": 1, "acceptable_roles": ["operations"], "division": "tech_ops",
             "linked_resource_ids": [], "sod_tags": [], "created_at": "2025-01-01T00:00:00+00:00",
             "updated_at": "2025-01-01T00:00:00+00:00"},
            {"id": "ENT-2", "name": "Reporting", "pbl_description": "Reporting access.",
             "access_tier": 4, "acceptable_roles": ["developer"], "division": "tech_dev",
             "linked_resource_ids": [], "sod_tags": [], "created_at": "2025-01-01T00:00:00+00:00",
             "updated_at": "2025-01-01T00:00:00+00:00"},
        ],
        "cmdb_resources.json": [
            {"id": "RES-1", "name": "Prod DB", "type": "database", "criticality": "critical",
             "owner_division": "tech_ops", "environment": "prod", "linked_entitlement_ids": ["ENT-1"],
             "description": "Production database."},
        ],
        "assignments.json": [
            {"id": "ASN-1", "employee_id": "EMP-1", "entitlement_id": "ENT-1",
             "granted_at": "2024-01-01T00:00:00+00:00", "granted_by": "system",
             "last_certified_at": None, "active": True},
            {"id": "ASN-2", "employee_id": "EMP-2", "entitlement_id": "ENT-2",
             "granted_at": "2024-01-01T00:00:00+00:00", "granted_by": "system",
             "last_certified_at": None, "active": True},
            {"id": "ASN-3", "employee_id": "EMP-1", "entitlement_id": "ENT-2",
             "granted_at": "2024-01-01T00:00:00+00:00", "granted_by": "system",
             "last_certified_at": None, "active": False},
        ],
        "violations.json": [
            _violation("VIO-1", "high", "open", "employee", "EMP-1", "HR-01", "A direct finding", "2026-01-03"),
            _violation("VIO-2", "high", "pending_approval", "assignment", "ASN-1", "TOX-01", "A pending finding", "2026-01-04"),
            _violation("VIO-3", "medium", "approved", "entitlement", "ENT-1", "ENT-Q-01", "Catalog issue", "2026-01-02"),
            _violation("VIO-4", "low", "manual_repair", "resource", "RES-1", "CMDB-01", "Resource issue", "2026-01-01"),
            _violation("VIO-5", "critical", "resolved", "assignment", "ASN-2", "TOX-02", "Resolved issue", "2025-12-31"),
            _violation("VIO-6", "low", "rejected", "entitlement", "ENT-2", "ENT-Q-02", "Rejected catalog issue", "2025-12-30"),
        ],
    }
    for name, contents in files.items():
        (tmp_path / name).write_text(json.dumps(contents))


def _violation(violation_id, severity, state, target_type, target_id, rule_id, reason, date):
    return {
        "id": violation_id, "rule_id": rule_id, "rule_name": f"{rule_id} rule", "severity": severity,
        "detected_at": f"{date}T00:00:00+00:00", "target_type": target_type, "target_id": target_id,
        "explanation": reason, "evidence": {}, "recommended_action": "route_to_compliance",
        "suggested_fix": {}, "workflow_state": state, "workflow_history": [], "appian_case_id": None,
    }


@pytest.fixture
def store(tmp_path):
    _write_fixture(tmp_path)
    return JsonStore(tmp_path)


@pytest.mark.asyncio
async def test_dashboard_query_filters_kpis_rows_but_not_its_own_severity_series(store):
    """A severity filter must not hide alternative severity segments in its chart."""
    filters = FindingFilters(severities=frozenset({"high"}), rules=frozenset())
    result = await load_dashboard_query(store, filters)

    assert result.kpis.total_findings == 2
    assert result.rows[0]["severity"] == "High"
    assert result.series["severity"] == [
        {"key": "high", "label": "High", "count": 2},
        {"key": "medium", "label": "Medium", "count": 1},
        {"key": "low", "label": "Low", "count": 1},
    ]
    assert [row["violationId"] for row in result.rows] == ["VIO-2", "VIO-1"]


@pytest.mark.asyncio
async def test_dashboard_query_facets_each_chart_only_on_its_own_dimension(store):
    """Each chart keeps alternatives for itself but honors every other active filter."""
    violations = json.loads((store.data_dir / "violations.json").read_text())
    violations.extend([
        _violation("VIO-7", "medium", "pending_approval", "assignment", "ASN-1", "TOX-01", "Medium peer", "2026-01-05"),
        _violation("VIO-8", "high", "open", "assignment", "ASN-1", "TOX-01", "Open peer", "2026-01-06"),
        _violation("VIO-9", "high", "pending_approval", "entitlement", "ENT-1", "TOX-01", "Catalog peer", "2026-01-07"),
        _violation("VIO-10", "high", "pending_approval", "assignment", "ASN-1", "HR-01", "Rule peer", "2026-01-08"),
    ])
    await store.write("violations.json", violations)
    result = await load_dashboard_query(
        store,
        FindingFilters(
            severities=frozenset({"high"}), states=frozenset({"pending_approval"}),
            target_types=frozenset({"assignment"}), rules=frozenset({"tox-01"}),
        ),
    )

    assert [row["violationId"] for row in result.rows] == ["VIO-2"]
    assert result.series["severity"] == [
        {"key": "high", "label": "High", "count": 1},
        {"key": "medium", "label": "Medium", "count": 1},
    ]
    assert result.series["targetType"] == [
        {"key": "assignment", "label": "Assignment", "count": 1},
        {"key": "entitlement", "label": "Entitlement", "count": 1},
    ]
    assert result.series["rule"] == [
        {"key": "hr-01", "label": "HR-01 rule", "count": 1},
        {"key": "tox-01", "label": "TOX-01 rule", "count": 1},
    ]
    assert result.series["workflow"] == [
        {"key": "not_started", "label": "Not started", "count": 1},
        {"key": "in_progress", "label": "In progress", "count": 1},
        {"key": "complete", "label": "Complete", "count": 0},
    ]


@pytest.mark.asyncio
async def test_dashboard_query_reports_workflow_coverage_catalog_and_empty_metadata(store):
    """KPI rows default active while the workflow facet keeps terminal alternatives."""
    result = await load_dashboard_query(store, FindingFilters())

    assert result.kpis.total_findings == 4
    assert result.series["workflow"] == [
        {"key": "not_started", "label": "Not started", "count": 1},
        {"key": "in_progress", "label": "In progress", "count": 3},
        {"key": "complete", "label": "Complete", "count": 2},
    ]
    assert result.entitlement_coverage == {"total": 2, "withFindings": 1, "withoutFindings": 1}
    assert [row["violationId"] for row in result.catalog_findings] == ["VIO-3"]
    assert result.pagination == {"page": 1, "pageSize": 50, "total": 4, "totalPages": 1}

    empty = await load_dashboard_query(
        store, FindingFilters(rules=frozenset({"missing"}), page_size=2),
    )
    assert empty.rows == []
    assert empty.pagination == {"page": 1, "pageSize": 2, "total": 0, "totalPages": 0}


@pytest.mark.asyncio
async def test_health_query_reports_contract_kpis_and_assignment_status_universe(store):
    """Health instruments must describe assignments and combine high/critical risk."""
    result = await load_dashboard_query(store, FindingFilters())

    assert result.kpis.total_assignments == 3
    assert result.kpis.high_critical_findings == 2
    assert result.kpis.catalog_findings == 1
    assert result.series["assignmentStatus"] == [
        {"key": "clean", "label": "Clean", "count": 2},
        {"key": "open", "label": "Open", "count": 0},
        {"key": "pending_approval", "label": "Pending Approval", "count": 0},
        {"key": "manual_repair", "label": "Manual Repair", "count": 1},
    ]


@pytest.mark.asyncio
async def test_assignment_status_and_coverage_filters_are_or_within_and_self_faceted(store):
    """Clean slices stay visible while selected portfolio dimensions narrow compatible rows."""
    manual_assignments = await load_dashboard_query(
        store,
        FindingFilters(assignment_statuses=frozenset({"manual_repair"})),
    )
    assert {row["violationId"] for row in manual_assignments.rows} == {
        "VIO-1",
        "VIO-2",
        "VIO-3",
        "VIO-4",
    }
    assert manual_assignments.kpis.total_assignments == 1
    assert manual_assignments.series["assignmentStatus"] == [
        {"key": "clean", "label": "Clean", "count": 2},
        {"key": "open", "label": "Open", "count": 0},
        {"key": "pending_approval", "label": "Pending Approval", "count": 0},
        {"key": "manual_repair", "label": "Manual Repair", "count": 1},
    ]

    clean_assignments = await load_dashboard_query(
        store,
        FindingFilters(assignment_statuses=frozenset({"clean"})),
    )
    assert clean_assignments.rows == []
    assert clean_assignments.kpis.total_assignments == 2
    assert clean_assignments.series["assignmentStatus"] == manual_assignments.series[
        "assignmentStatus"
    ]

    catalog = await load_dashboard_query(
        store,
        FindingFilters(coverage=frozenset({"with_findings"})),
    )
    assert {row["violationId"] for row in catalog.rows} == {
        "VIO-1",
        "VIO-2",
        "VIO-3",
        "VIO-4",
    }
    assert catalog.entitlement_coverage == {
        "total": 2,
        "withFindings": 1,
        "withoutFindings": 1,
    }

    clean_catalog = await load_dashboard_query(
        store,
        FindingFilters(coverage=frozenset({"clean"})),
    )
    assert clean_catalog.rows == []
    assert clean_catalog.entitlement_coverage == catalog.entitlement_coverage


@pytest.mark.asyncio
async def test_assignment_and_coverage_relationships_span_all_target_types_and_cmdb_links(store):
    """Every active target relationship must propagate to its assignment and catalog records."""
    entitlements = await store.read("entitlements.json")
    entitlements[1]["linked_resource_ids"] = ["RES-2"]
    await store.write("entitlements.json", entitlements)
    resources = await store.read("cmdb_resources.json")
    resources.append(
        {
            "id": "RES-2",
            "name": "Reporting API",
            "type": "api",
            "criticality": "high",
            "owner_division": "tech_dev",
            "environment": "prod",
            "linked_entitlement_ids": [],
            "description": "Reporting API.",
        }
    )
    await store.write("cmdb_resources.json", resources)
    await store.write(
        "violations.json",
        [
            _violation(
                "VIO-EMP",
                "high",
                "open",
                "employee",
                "EMP-1",
                "HR-01",
                "Holder finding",
                "2026-02-01",
            ),
            _violation(
                "VIO-ASN",
                "medium",
                "pending_approval",
                "assignment",
                "ASN-2",
                "HR-02",
                "Assignment finding",
                "2026-02-02",
            ),
            _violation(
                "VIO-ENT",
                "low",
                "approved",
                "entitlement",
                "ENT-1",
                "ENT-Q-01",
                "Entitlement finding",
                "2026-02-03",
            ),
            _violation(
                "VIO-RES",
                "critical",
                "manual_repair",
                "resource",
                "RES-2",
                "CMDB-01",
                "Linked resource finding",
                "2026-02-04",
            ),
        ],
    )

    result = await load_dashboard_query(store, FindingFilters())

    assert result.entitlement_coverage == {
        "total": 2,
        "withFindings": 2,
        "withoutFindings": 0,
    }
    assert result.kpis.catalog_findings == 1
    assert result.series["assignmentStatus"] == [
        {"key": "clean", "label": "Clean", "count": 1},
        {"key": "open", "label": "Open", "count": 0},
        {"key": "pending_approval", "label": "Pending Approval", "count": 0},
        {"key": "approved", "label": "Approved", "count": 1},
        {"key": "manual_repair", "label": "Manual Repair", "count": 1},
    ]

    approved = await load_dashboard_query(
        store,
        FindingFilters(assignment_statuses=frozenset({"approved"})),
    )
    assert {row["violationId"] for row in approved.rows} == {"VIO-EMP", "VIO-ENT"}
    assert approved.series["assignmentStatus"] == result.series["assignmentStatus"]

    manual = await load_dashboard_query(
        store,
        FindingFilters(assignment_statuses=frozenset({"manual_repair"})),
    )
    assert {row["violationId"] for row in manual.rows} == {"VIO-ASN", "VIO-RES"}

    covered = await load_dashboard_query(
        store,
        FindingFilters(coverage=frozenset({"with_findings"})),
    )
    assert {row["violationId"] for row in covered.rows} == {
        "VIO-EMP",
        "VIO-ASN",
        "VIO-ENT",
        "VIO-RES",
    }
    assert covered.entitlement_coverage == result.entitlement_coverage

    clean_assignments = await load_dashboard_query(
        store,
        FindingFilters(assignment_statuses=frozenset({"clean"})),
    )
    assert clean_assignments.rows == []
    assert clean_assignments.series["assignmentStatus"] == result.series["assignmentStatus"]

    clean_coverage = await load_dashboard_query(
        store,
        FindingFilters(coverage=frozenset({"clean"})),
    )
    assert clean_coverage.rows == []
    assert clean_coverage.entitlement_coverage == result.entitlement_coverage


@pytest.mark.asyncio
async def test_dashboard_query_paginates_sorted_rows_without_changing_aggregates(store):
    """Changing table pages must never change the aggregate findings population."""
    first = await load_dashboard_query(store, FindingFilters(page=1, page_size=2))
    second = await load_dashboard_query(store, FindingFilters(page=2, page_size=2))

    assert [row["violationId"] for row in first.rows] == ["VIO-2", "VIO-1"]
    assert [row["violationId"] for row in second.rows] == ["VIO-3", "VIO-4"]
    assert first.kpis.total_findings == second.kpis.total_findings == 4
    assert first.series == second.series
    assert first.pagination == {"page": 1, "pageSize": 2, "total": 4, "totalPages": 2}
    assert second.pagination == {"page": 2, "pageSize": 2, "total": 4, "totalPages": 2}


@pytest.mark.asyncio
async def test_dashboard_query_returns_empty_rows_for_a_page_past_the_last(store):
    """An out-of-range page must retain useful total/page metadata rather than wrap."""
    result = await load_dashboard_query(store, FindingFilters(page=3, page_size=2))

    assert result.rows == []
    assert result.pagination == {"page": 3, "pageSize": 2, "total": 4, "totalPages": 2}


def test_finding_filters_normalize_invalid_pagination_inputs():
    """Non-positive pagination input must not create negative or zero-size slices."""
    filters = FindingFilters(page=0, page_size=0)

    assert filters.page == 1
    assert filters.page_size == 1


@pytest.mark.asyncio
async def test_persona_scope_includes_direct_active_assignment_and_active_entitlement_findings(store):
    """Persona scope must not leak other users or inactive-entitlement findings."""
    result = await load_dashboard_query(store, FindingFilters(), persona_id="EMP-1")

    assert [row["violationId"] for row in result.rows] == ["VIO-2", "VIO-1", "VIO-3"]


@pytest.mark.asyncio
async def test_personas_are_active_and_sorted_with_public_fields_only(store):
    """The picker must not expose terminated employees or sensitive HR fields."""
    assert await load_personas(store) == [
        {"id": "EMP-1", "fullName": "Ada Lovelace", "division": "tech_ops", "role": "operations"},
        {"id": "EMP-2", "fullName": "Grace Hopper", "division": "tech_dev", "role": "developer"},
    ]
