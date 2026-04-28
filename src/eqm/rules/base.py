"""Rule contract and shared snapshot type."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from eqm.models import (
    Assignment,
    CMDBResource,
    Entitlement,
    HREmployee,
    RecommendedAction,
    Severity,
    Violation,
)


@dataclass(frozen=True, slots=True)
class DataSnapshot:
    entitlements: tuple[Entitlement, ...]
    hr_employees: tuple[HREmployee, ...]
    cmdb_resources: tuple[CMDBResource, ...]
    assignments: tuple[Assignment, ...]

    def __init__(self, entitlements: Iterable[Entitlement],
                 hr_employees: Iterable[HREmployee],
                 cmdb_resources: Iterable[CMDBResource],
                 assignments: Iterable[Assignment]) -> None:
        object.__setattr__(self, "entitlements", tuple(entitlements))
        object.__setattr__(self, "hr_employees", tuple(hr_employees))
        object.__setattr__(self, "cmdb_resources", tuple(cmdb_resources))
        object.__setattr__(self, "assignments", tuple(assignments))

    def entitlement_by_id(self, ent_id: str) -> Entitlement | None:
        return next((e for e in self.entitlements if e.id == ent_id), None)

    def employee_by_id(self, emp_id: str) -> HREmployee | None:
        return next((e for e in self.hr_employees if e.id == emp_id), None)

    def resource_by_id(self, res_id: str) -> CMDBResource | None:
        return next((r for r in self.cmdb_resources if r.id == res_id), None)


@runtime_checkable
class Rule(Protocol):
    id: str
    name: str
    severity: Severity
    category: str
    recommended_action: RecommendedAction

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]: ...


def now_utc() -> datetime:
    return datetime.now(UTC)


_VIO_RE = re.compile(r"VIO-(\d+)")


def next_violation_id(existing_ids: list[str]) -> str:
    nums = [int(m.group(1)) for vid in existing_ids if (m := _VIO_RE.match(vid))]
    return f"VIO-{(max(nums) + 1) if nums else 1:05d}"
