from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from eqm.ctadmin.repairs import (
    REPAIR_BUILDERS,
    RecordMutation,
    RepairValidationError,
    apply_plan,
    build_repair_plan,
)
from eqm.models import (
    AccessTier,
    Assignment,
    CMDBResource,
    Criticality,
    Division,
    EmployeeStatus,
    Entitlement,
    HREmployee,
    RecommendedAction,
    ResourceType,
    Role,
    RoleHistoryEntry,
    Severity,
    Violation,
)
from eqm.seed import SeedBundle

NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)


def entitlement(**changes: object) -> Entitlement:
    values: dict[str, object] = {
        "id": "ENT-1",
        "name": "Ledger reader",
        "pbl_description": "bad",
        "access_tier": AccessTier.ADMIN,
        "acceptable_roles": [Role.OPERATIONS],
        "division": Division.TECH_OPS,
        "linked_resource_ids": ["RES-1"],
        "sod_tags": [],
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return Entitlement(**values)


def employee(**changes: object) -> HREmployee:
    values: dict[str, object] = {
        "id": "EMP-1",
        "full_name": "Casey Example",
        "email": "casey@example.com",
        "current_role": Role.OPERATIONS,
        "current_division": Division.TECH_OPS,
        "status": EmployeeStatus.ACTIVE,
        "role_history": [],
        "manager_id": "EMP-MGR",
        "hired_at": NOW,
        "terminated_at": None,
    }
    values.update(changes)
    return HREmployee(**values)


def resource(**changes: object) -> CMDBResource:
    values: dict[str, object] = {
        "id": "RES-1",
        "name": "Ledger API",
        "type": ResourceType.API,
        "criticality": Criticality.CRITICAL,
        "owner_division": Division.FINANCE,
        "environment": "prod",
        "linked_entitlement_ids": ["ENT-1"],
        "description": "Finance ledger API",
    }
    values.update(changes)
    return CMDBResource(**values)


def assignment(**changes: object) -> Assignment:
    values: dict[str, object] = {
        "id": "ASN-1",
        "employee_id": "EMP-1",
        "entitlement_id": "ENT-1",
        "granted_at": NOW,
        "granted_by": "system",
        "last_certified_at": None,
        "active": True,
    }
    values.update(changes)
    return Assignment(**values)


def bundle(
    *,
    entitlements: list[Entitlement] | None = None,
    employees: list[HREmployee] | None = None,
    resources: list[CMDBResource] | None = None,
    assignments: list[Assignment] | None = None,
) -> SeedBundle:
    return SeedBundle(
        entitlements=entitlements if entitlements is not None else [entitlement()],
        hr_employees=employees if employees is not None else [employee()],
        cmdb_resources=resources if resources is not None else [resource()],
        assignments=assignments if assignments is not None else [],
    )


def violation(
    rule_id: str,
    *,
    target_type: str = "entitlement",
    target_id: str = "ENT-1",
    evidence: dict[str, object] | None = None,
) -> Violation:
    return Violation(
        id=f"VIO-{rule_id}",
        rule_id=rule_id,
        rule_name=rule_id,
        severity=Severity.HIGH,
        detected_at=NOW,
        target_type=target_type,
        target_id=target_id,
        explanation="fixture violation",
        evidence=evidence or {},
        recommended_action=RecommendedAction.ROUTE_TO_COMPLIANCE,
        suggested_fix={},
    )


@pytest.mark.parametrize(
    ("rule_id", "existing", "evidence", "submission", "changes", "summary"),
    [
        (
            "ENT-Q-01",
            entitlement(pbl_description="bad"),
            {"pbl_description": "bad", "reasons": ["length=3 < 20"]},
            {"pbl_description": "Read-only access to Ledger API for finance analysts."},
            {"pbl_description": "Read-only access to Ledger API for finance analysts."},
            "Update the PBL description for entitlement ENT-1.",
        ),
        (
            "ENT-Q-02",
            entitlement(pbl_description="Full control of Ledger API", access_tier=AccessTier.ADMIN),
            {"access_tier": 1, "pbl_description": "Full control of Ledger API"},
            {"pbl_description": "Administrator access to Ledger API for operations engineers."},
            {"pbl_description": "Administrator access to Ledger API for operations engineers."},
            "Update the PBL description for entitlement ENT-1.",
        ),
        (
            "ENT-Q-03",
            entitlement(acceptable_roles=[Role.OPERATIONS, Role.CUSTOMER]),
            {
                "access_tier": 1,
                "acceptable_roles": ["operations", "customer"],
                "forbidden_roles": ["customer"],
            },
            {"acceptable_roles": ["operations"]},
            {"acceptable_roles": ["operations"]},
            "Update acceptable roles for entitlement ENT-1.",
        ),
        (
            "ENT-Q-04",
            entitlement(
                division=Division.HR,
                acceptable_roles=[Role.DEVELOPER, Role.OPERATIONS],
            ),
            {
                "division": "hr",
                "access_tier": 1,
                "acceptable_roles": ["developer", "operations"],
            },
            {"acceptable_roles": ["operations"]},
            {"acceptable_roles": ["operations"]},
            "Remove incoherent roles from entitlement ENT-1.",
        ),
        (
            "ENT-Q-04",
            entitlement(
                division=Division.LEGAL_COMPLIANCE,
                access_tier=AccessTier.ADMIN,
            ),
            {
                "division": "legal_compliance",
                "access_tier": 1,
                "acceptable_roles": ["operations"],
                "prod_resources": ["RES-1"],
            },
            {"access_tier": 2},
            {"access_tier": 2},
            "Reduce the access tier for entitlement ENT-1 to Tier-2.",
        ),
        (
            "CMDB-02",
            entitlement(access_tier=AccessTier.GENERAL_RO),
            {
                "access_tier": 4,
                "offending_resources": [{"id": "RES-1", "criticality": "critical"}],
            },
            {"access_tier": 2},
            {"access_tier": 2},
            "Reduce the access tier for entitlement ENT-1 to Tier-2.",
        ),
    ],
)
def test_direct_edits_plan_exact_mutation(
    rule_id: str,
    existing: Entitlement,
    evidence: dict[str, object],
    submission: dict[str, object],
    changes: dict[str, object],
    summary: str,
) -> None:
    current = bundle(entitlements=[existing])

    plan = build_repair_plan(violation(rule_id, evidence=evidence), current, submission)

    assert plan.violation_key == (f"VIO-{rule_id}", rule_id, "ENT-1")
    assert plan.rule_id == rule_id
    assert plan.summary == summary
    assert plan.choice == submission
    assert plan.mutations == (RecordMutation("entitlements", "ENT-1", changes),)
    assert current.entitlements[0] == existing


@pytest.mark.parametrize(
    ("rule_id", "target", "evidence", "submission"),
    [
        (
            "ENT-Q-01",
            entitlement(pbl_description="bad"),
            {"pbl_description": "bad", "reasons": ["length=3 < 20"]},
            {"pbl_description": "[Owner — please rewrite this description.]"},
        ),
        (
            "ENT-Q-01",
            entitlement(pbl_description="bad"),
            {"pbl_description": "stale", "reasons": ["length=5 < 20"]},
            {"pbl_description": "Read-only access to Ledger API for finance analysts."},
        ),
        (
            "CMDB-02",
            entitlement(access_tier=AccessTier.GENERAL_RO),
            {"access_tier": 4, "offending_resources": [{"id": "RES-X", "criticality": "high"}]},
            {"access_tier": 2},
        ),
    ],
)
def test_direct_edits_reject_placeholder_or_stale_evidence(
    rule_id: str,
    target: Entitlement,
    evidence: dict[str, object],
    submission: dict[str, object],
) -> None:
    with pytest.raises(RepairValidationError):
        build_repair_plan(
            violation(rule_id, evidence=evidence),
            bundle(entitlements=[target]),
            submission,
        )


def test_ent_q_01_rejects_tampered_reasons_and_a_currently_clean_target() -> None:
    clean_text = "Read-only access to Ledger API for finance analysts."
    with pytest.raises(RepairValidationError, match="evidence|stale"):
        build_repair_plan(
            violation(
                "ENT-Q-01",
                evidence={"pbl_description": "bad", "reasons": ["length=4 < 20"]},
            ),
            bundle(entitlements=[entitlement(pbl_description="bad")]),
            {"pbl_description": clean_text},
        )

    with pytest.raises(RepairValidationError, match="no longer|current state"):
        build_repair_plan(
            violation(
                "ENT-Q-01",
                evidence={"pbl_description": clean_text, "reasons": []},
            ),
            bundle(entitlements=[entitlement(pbl_description=clean_text)]),
            {"pbl_description": "Read-only access to Ledger API for accounting reviewers."},
        )


def test_ent_q_02_rejects_tampered_evidence_and_a_currently_clean_target() -> None:
    clean_text = "Administrator access to Ledger API for operations engineers."
    with pytest.raises(RepairValidationError, match="evidence|stale"):
        build_repair_plan(
            violation(
                "ENT-Q-02",
                evidence={"access_tier": 1, "pbl_description": "tampered"},
            ),
            bundle(entitlements=[entitlement(pbl_description="Full control of Ledger API")]),
            {"pbl_description": clean_text},
        )

    with pytest.raises(RepairValidationError, match="no longer|current state"):
        build_repair_plan(
            violation(
                "ENT-Q-02",
                evidence={"access_tier": 1, "pbl_description": clean_text},
            ),
            bundle(entitlements=[entitlement(pbl_description=clean_text)]),
            {"pbl_description": "Administrator access to Ledger API for platform engineers."},
        )


def test_ent_q_03_allows_only_exact_removal_of_evidence_forbidden_roles() -> None:
    current = bundle(
        entitlements=[
            entitlement(acceptable_roles=[Role.OPERATIONS, Role.CUSTOMER, Role.DEVELOPER])
        ]
    )
    finding = violation(
        "ENT-Q-03",
        evidence={
            "access_tier": 1,
            "acceptable_roles": ["operations", "customer", "developer"],
            "forbidden_roles": ["customer"],
        },
    )

    with pytest.raises(RepairValidationError, match="exact|forbidden"):
        build_repair_plan(finding, current, {"acceptable_roles": ["developer"]})

    plan = build_repair_plan(
        finding,
        current,
        {"acceptable_roles": ["operations", "developer"]},
    )
    assert plan.mutations == (
        RecordMutation(
            "entitlements",
            "ENT-1",
            {"acceptable_roles": ["operations", "developer"]},
        ),
    )


def test_ent_q_04_hr_allows_only_removing_developer() -> None:
    current = bundle(
        entitlements=[
            entitlement(
                division=Division.HR,
                acceptable_roles=[Role.OPERATIONS, Role.DEVELOPER, Role.BUSINESS_USER],
            )
        ]
    )
    finding = violation(
        "ENT-Q-04",
        evidence={
            "division": "hr",
            "access_tier": 1,
            "acceptable_roles": ["operations", "developer", "business_user"],
        },
    )

    with pytest.raises(RepairValidationError, match="exact|developer"):
        build_repair_plan(finding, current, {"acceptable_roles": ["business_user"]})

    plan = build_repair_plan(
        finding,
        current,
        {"acceptable_roles": ["operations", "business_user"]},
    )
    assert plan.mutations == (
        RecordMutation(
            "entitlements",
            "ENT-1",
            {"acceptable_roles": ["operations", "business_user"]},
        ),
    )


def test_ent_q_04_legal_requires_tier_two() -> None:
    finding = violation(
        "ENT-Q-04",
        evidence={
            "division": "legal_compliance",
            "access_tier": 1,
            "acceptable_roles": ["operations"],
            "prod_resources": ["RES-1"],
        },
    )

    with pytest.raises(RepairValidationError, match="Tier-2"):
        build_repair_plan(
            finding,
            bundle(
                entitlements=[
                    entitlement(
                        division=Division.LEGAL_COMPLIANCE,
                        access_tier=AccessTier.ADMIN,
                    )
                ]
            ),
            {"access_tier": 3},
        )


@pytest.mark.parametrize("rule_id", ["HR-01", "HR-02", "HR-04"])
def test_assignment_rules_revoke_only_the_target(rule_id: str) -> None:
    target = assignment()
    peer = assignment(id="ASN-2")
    ent_by_rule = {
        "HR-01": entitlement(acceptable_roles=[Role.DEVELOPER]),
        "HR-02": entitlement(division=Division.FINANCE),
        "HR-04": entitlement(),
    }
    emp_by_rule = {
        "HR-01": employee(current_role=Role.OPERATIONS),
        "HR-02": employee(current_division=Division.TECH_OPS),
        "HR-04": employee(status=EmployeeStatus.TERMINATED),
    }
    current = bundle(
        entitlements=[ent_by_rule[rule_id]],
        employees=[emp_by_rule[rule_id]],
        assignments=[target, peer],
    )
    evidence_by_rule: dict[str, dict[str, object]] = {
        "HR-01": {
            "employee_id": "EMP-1",
            "employee_role": "operations",
            "entitlement_id": "ENT-1",
            "acceptable_roles": ["developer"],
        },
        "HR-02": {
            "employee_id": "EMP-1",
            "employee_division": "tech_ops",
            "entitlement_id": "ENT-1",
            "entitlement_division": "finance",
        },
        "HR-04": {
            "employee_id": "EMP-1",
            "terminated_at": None,
            "entitlement_id": "ENT-1",
        },
    }

    plan = build_repair_plan(
        violation(
            rule_id,
            target_type="assignment",
            target_id="ASN-1",
            evidence=evidence_by_rule[rule_id],
        ),
        current,
        {},
    )

    assert plan.mutations == (RecordMutation("assignments", "ASN-1", {"active": False}),)
    assert plan.summary == "Revoke assignment ASN-1."


def test_hr03_requires_manager_acknowledgement() -> None:
    changed_at = NOW - timedelta(days=60)
    granted_at = NOW - timedelta(days=90)
    current = bundle(
        entitlements=[entitlement(acceptable_roles=[Role.DEVELOPER])],
        employees=[
            employee(
                current_role=Role.OPERATIONS,
                role_history=[
                    RoleHistoryEntry(
                        role=Role.DEVELOPER,
                        division=Division.TECH_DEV,
                        started_at=NOW - timedelta(days=365),
                        ended_at=changed_at,
                    ),
                    RoleHistoryEntry(
                        role=Role.OPERATIONS,
                        division=Division.TECH_OPS,
                        started_at=changed_at,
                    ),
                ],
            )
        ],
        assignments=[assignment(granted_at=granted_at)],
    )
    finding = violation(
        "HR-03",
        target_type="assignment",
        target_id="ASN-1",
        evidence={
            "employee_id": "EMP-1",
            "current_role": "operations",
            "prior_roles": ["developer"],
            "last_role_change_at": changed_at.isoformat(),
            "granted_at": granted_at.isoformat(),
        },
    )

    with pytest.raises(RepairValidationError, match="manager"):
        build_repair_plan(finding, current, {})

    plan = build_repair_plan(finding, current, {"manager_confirmed": True})
    assert plan.mutations == (RecordMutation("assignments", "ASN-1", {"active": False}),)


def test_hr03_rejects_a_role_change_less_than_thirty_days_old() -> None:
    changed_at = datetime.now(UTC) - timedelta(days=10)
    granted_at = changed_at - timedelta(days=30)
    current = bundle(
        entitlements=[entitlement(acceptable_roles=[Role.DEVELOPER])],
        employees=[
            employee(
                current_role=Role.OPERATIONS,
                role_history=[
                    RoleHistoryEntry(
                        role=Role.DEVELOPER,
                        division=Division.TECH_DEV,
                        started_at=changed_at - timedelta(days=365),
                        ended_at=changed_at,
                    ),
                    RoleHistoryEntry(
                        role=Role.OPERATIONS,
                        division=Division.TECH_OPS,
                        started_at=changed_at,
                    ),
                ],
            )
        ],
        assignments=[assignment(granted_at=granted_at)],
    )
    finding = violation(
        "HR-03",
        target_type="assignment",
        target_id="ASN-1",
        evidence={
            "employee_id": "EMP-1",
            "current_role": "operations",
            "prior_roles": ["developer"],
            "last_role_change_at": changed_at.isoformat(),
            "granted_at": granted_at.isoformat(),
        },
    )

    with pytest.raises(RepairValidationError, match="30|recent|no longer"):
        build_repair_plan(finding, current, {"manager_confirmed": True})


def test_assignment_repair_rejects_an_inactive_stale_target() -> None:
    with pytest.raises(RepairValidationError, match="inactive|stale"):
        build_repair_plan(
            violation(
                "HR-04",
                target_type="assignment",
                target_id="ASN-1",
                evidence={"employee_id": "EMP-1", "terminated_at": None, "entitlement_id": "ENT-1"},
            ),
            bundle(
                employees=[employee(status=EmployeeStatus.TERMINATED)],
                assignments=[assignment(active=False)],
            ),
            {},
        )


def tox01_bundle() -> SeedBundle:
    return bundle(
        entitlements=[
            entitlement(
                id="ENT-L",
                access_tier=AccessTier.GENERAL_RO,
                sod_tags=["payment_initiate"],
            ),
            entitlement(
                id="ENT-R",
                access_tier=AccessTier.GENERAL_RO,
                sod_tags=["payment_approve"],
            ),
        ],
        assignments=[
            assignment(id="ASN-L", entitlement_id="ENT-L"),
            assignment(id="ASN-R", entitlement_id="ENT-R"),
        ],
    )


def tox02_bundle() -> SeedBundle:
    return bundle(
        entitlements=[
            entitlement(id="ENT-D", acceptable_roles=[Role.DEVELOPER]),
            entitlement(id="ENT-O", acceptable_roles=[Role.OPERATIONS]),
        ],
        assignments=[
            assignment(id="ASN-D", entitlement_id="ENT-D"),
            assignment(id="ASN-O", entitlement_id="ENT-O"),
        ],
    )


def tox03_bundle() -> SeedBundle:
    return bundle(
        entitlements=[
            entitlement(id="ENT-1", division=Division.FINANCE),
            entitlement(id="ENT-2", division=Division.HR),
            entitlement(id="ENT-3", division=Division.LEGAL_COMPLIANCE),
        ],
        assignments=[
            assignment(id="ASN-1", entitlement_id="ENT-1"),
            assignment(id="ASN-2", entitlement_id="ENT-2"),
            assignment(id="ASN-3", entitlement_id="ENT-3"),
        ],
    )


@pytest.mark.parametrize(
    ("side", "assignment_id"),
    [("left", "ASN-L"), ("right", "ASN-R")],
)
def test_tox01_revokes_the_selected_evidence_side(side: str, assignment_id: str) -> None:
    plan = build_repair_plan(
        violation(
            "TOX-01",
            target_type="employee",
            target_id="EMP-1",
            evidence={
                "sod_pair": ["payment_initiate", "payment_approve"],
                "entitlement_ids": ["ENT-L", "ENT-R"],
            },
        ),
        tox01_bundle(),
        {"side": side},
    )

    assert plan.mutations == (RecordMutation("assignments", assignment_id, {"active": False}),)


@pytest.mark.parametrize(
    ("side", "assignment_id"),
    [("developer", "ASN-D"), ("operations", "ASN-O")],
)
def test_tox02_revokes_the_selected_evidence_side(side: str, assignment_id: str) -> None:
    plan = build_repair_plan(
        violation(
            "TOX-02",
            target_type="employee",
            target_id="EMP-1",
            evidence={
                "resource_id": "RES-1",
                "developer_admin_entitlements": ["ENT-D"],
                "operations_admin_entitlements": ["ENT-O"],
            },
        ),
        tox02_bundle(),
        {"side": side},
    )

    assert plan.mutations == (RecordMutation("assignments", assignment_id, {"active": False}),)


def test_tox03_accepts_only_evidence_assignments_that_leave_two_divisions() -> None:
    finding = violation(
        "TOX-03",
        target_type="employee",
        target_id="EMP-1",
        evidence={
            "divisions": ["finance", "hr", "legal_compliance"],
            "entitlement_ids": ["ENT-1", "ENT-2", "ENT-3"],
        },
    )

    plan = build_repair_plan(finding, tox03_bundle(), {"assignment_ids": ["ASN-3"]})
    assert plan.mutations == (RecordMutation("assignments", "ASN-3", {"active": False}),)

    with pytest.raises(RepairValidationError, match="two|2"):
        build_repair_plan(finding, tox03_bundle(), {"assignment_ids": []})
    with pytest.raises(RepairValidationError, match="evidence"):
        build_repair_plan(finding, tox03_bundle(), {"assignment_ids": ["ASN-D"]})


def test_tox03_rejects_a_current_footprint_of_only_two_divisions() -> None:
    current = bundle(
        entitlements=[
            entitlement(id="ENT-1", division=Division.FINANCE),
            entitlement(id="ENT-2", division=Division.HR),
        ],
        assignments=[
            assignment(id="ASN-1", entitlement_id="ENT-1"),
            assignment(id="ASN-2", entitlement_id="ENT-2"),
        ],
    )
    finding = violation(
        "TOX-03",
        target_type="employee",
        target_id="EMP-1",
        evidence={
            "divisions": ["finance", "hr"],
            "entitlement_ids": ["ENT-1", "ENT-2"],
        },
    )

    with pytest.raises(RepairValidationError, match="no longer|three|3"):
        build_repair_plan(finding, current, {"assignment_ids": ["ASN-2"]})


def test_toxic_repairs_reject_a_stale_evidence_entitlement() -> None:
    with pytest.raises(RepairValidationError, match="evidence|stale"):
        build_repair_plan(
            violation(
                "TOX-01",
                target_type="employee",
                target_id="EMP-1",
                evidence={
                    "sod_pair": ["payment_initiate", "payment_approve"],
                    "entitlement_ids": ["ENT-L", "ENT-MISSING"],
                },
            ),
            tox01_bundle(),
            {"side": "left"},
        )


def test_tox01_rejects_a_tampered_pair_order() -> None:
    with pytest.raises(RepairValidationError, match="evidence|stale"):
        build_repair_plan(
            violation(
                "TOX-01",
                target_type="employee",
                target_id="EMP-1",
                evidence={
                    "sod_pair": ["payment_approve", "payment_initiate"],
                    "entitlement_ids": ["ENT-L", "ENT-R"],
                },
            ),
            tox01_bundle(),
            {"side": "left"},
        )


def test_cmdb01_adds_reciprocal_links_once() -> None:
    current = bundle(
        entitlements=[entitlement(linked_resource_ids=[])],
        resources=[resource(linked_entitlement_ids=[])],
    )
    finding = violation(
        "CMDB-01",
        evidence={"declared_links": [], "valid_links": []},
    )

    plan = build_repair_plan(finding, current, {"resource_id": "RES-1"})

    assert plan.mutations == (
        RecordMutation("entitlements", "ENT-1", {"linked_resource_ids": ["RES-1"]}),
        RecordMutation("resources", "RES-1", {"linked_entitlement_ids": ["ENT-1"]}),
    )
    updated = apply_plan(current, plan)
    assert current.entitlements[0].linked_resource_ids == []
    assert current.cmdb_resources[0].linked_entitlement_ids == []
    assert updated.entitlements[0].linked_resource_ids == ["RES-1"]
    assert updated.cmdb_resources[0].linked_entitlement_ids == ["ENT-1"]


def test_cmdb01_rejects_an_unknown_resource() -> None:
    with pytest.raises(RepairValidationError, match="resource"):
        build_repair_plan(
            violation("CMDB-01", evidence={"declared_links": [], "valid_links": []}),
            bundle(entitlements=[entitlement(linked_resource_ids=[])]),
            {"resource_id": "RES-MISSING"},
        )


def test_apply_plan_returns_a_new_bundle_and_changes_only_target_record() -> None:
    current = bundle(
        employees=[employee(status=EmployeeStatus.TERMINATED)],
        assignments=[assignment(), assignment(id="ASN-2")],
    )
    plan = build_repair_plan(
        violation(
            "HR-04",
            target_type="assignment",
            target_id="ASN-1",
            evidence={"employee_id": "EMP-1", "terminated_at": None, "entitlement_id": "ENT-1"},
        ),
        current,
        {},
    )

    updated = apply_plan(current, plan)

    assert updated is not current
    assert [item.active for item in updated.assignments] == [False, True]
    assert [item.active for item in current.assignments] == [True, True]


def test_registry_covers_all_rules() -> None:
    assert set(REPAIR_BUILDERS) == {
        "ENT-Q-01",
        "ENT-Q-02",
        "ENT-Q-03",
        "ENT-Q-04",
        "TOX-01",
        "TOX-02",
        "TOX-03",
        "HR-01",
        "HR-02",
        "HR-03",
        "HR-04",
        "CMDB-01",
        "CMDB-02",
    }
