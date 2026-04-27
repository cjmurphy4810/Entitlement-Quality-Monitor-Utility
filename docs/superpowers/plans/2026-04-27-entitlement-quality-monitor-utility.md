# Entitlement Quality Monitor Utility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, fact-based rules engine over a simulated entitlement / HR / CMDB data fabric, exposed via FastAPI for Appian to consume, with a human-in-the-loop workflow state machine for remediation.

**Architecture:** A Python 3.12 package `eqm` providing five Pydantic-validated entities persisted as JSON files in `data/`, a registry of 13 deterministic rule classes, an engine that reconciles violations across runs (preserving Appian-side workflow state), a simulator with both scheduled drift and on-cue scenarios, a FastAPI app exposing read/write/simulator/sync endpoints, and a Jinja2 read-only dashboard. Deployed to Fly.io with a Fly volume for `/data`, plus a GitHub Actions cron for background drift commits.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Jinja2, Faker, GitPython, pytest, httpx, ruff, uv (package manager), Docker, Fly.io.

**Reference spec:** `docs/superpowers/specs/2026-04-27-entitlement-quality-monitor-utility-design.md`

---

## File Structure

```
.
├── pyproject.toml                 ← package + tool config
├── .gitignore
├── Dockerfile
├── fly.toml                       ← (already exists, will be updated)
├── README.md
├── data/                          ← seeded JSON files
│   ├── entitlements.json
│   ├── hr_employees.json
│   ├── cmdb_resources.json
│   ├── assignments.json
│   └── violations.json
├── src/eqm/
│   ├── __init__.py
│   ├── config.py                  ← env vars, paths, settings
│   ├── models.py                  ← Pydantic schemas + enums
│   ├── persistence.py             ← atomic JSON I/O + git push/pull
│   ├── seed.py                    ← Faker-based initial data
│   ├── rules/
│   │   ├── __init__.py            ← ALL_RULES registry
│   │   ├── base.py                ← Rule protocol, DataSnapshot, helpers
│   │   ├── entitlement_quality.py ← ENT-Q-01..04
│   │   ├── toxic_combinations.py  ← TOX-01..03
│   │   ├── hr_coherence.py        ← HR-01..04
│   │   └── cmdb_linkage.py        ← CMDB-01..02
│   ├── engine.py                  ← runs ALL_RULES, reconciles state
│   ├── simulator.py               ← drift mode mutations
│   ├── scenarios.py               ← named demo scenarios
│   ├── api.py                     ← FastAPI app
│   ├── workflow.py                ← Violation state machine
│   ├── cli.py                     ← `python -m eqm` entrypoint
│   └── dashboard/
│       ├── templates/
│       │   ├── base.html
│       │   ├── _control_bar.html
│       │   ├── overview.html
│       │   ├── entitlements.html
│       │   ├── hr.html
│       │   ├── cmdb.html
│       │   └── violations.html
│       └── static/
│           └── style.css
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_persistence.py
│   ├── test_seed.py
│   ├── rules/
│   │   ├── conftest.py
│   │   ├── test_ent_q_01.py … test_cmdb_02.py    ← 13 files
│   ├── test_engine.py
│   ├── test_simulator.py
│   ├── test_scenarios.py
│   ├── test_workflow.py
│   ├── test_api_reads.py
│   ├── test_api_writes.py
│   ├── test_api_simulate.py
│   └── test_dashboard.py
└── .github/workflows/
    └── simulate.yml
```

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/eqm/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "eqm"
version = "0.1.0"
description = "Entitlement Quality Monitor Utility — simulated data fabric + rules engine for Appian"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "jinja2>=3.1",
    "python-multipart>=0.0.20",
    "faker>=33",
    "gitpython>=3.1",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.7",
    "freezegun>=1.5",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/eqm"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "SIM"]
ignore = ["E501"]
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.env
.pytest_cache/
.ruff_cache/
*.egg-info/
dist/
build/
.DS_Store
```

- [ ] **Step 3: Create empty package init files**

`src/eqm/__init__.py`:
```python
"""Entitlement Quality Monitor Utility."""

__version__ = "0.1.0"
```

`tests/__init__.py`: (empty file)

- [ ] **Step 4: Install dependencies and verify import**

Run: `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
Expected: install succeeds, no errors.
Run: `python -c "import eqm; print(eqm.__version__)"`
Expected: `0.1.0`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore src/eqm/__init__.py tests/__init__.py
git commit -m "chore: scaffold eqm package with pyproject + dev deps"
```

---

## Task 2: Config module

**Files:**
- Create: `src/eqm/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from pathlib import Path

from eqm.config import Settings


def test_settings_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("EQM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EQM_BEARER_TOKEN", "test-token")
    s = Settings()
    assert s.data_dir == tmp_path
    assert s.bearer_token == "test-token"
    assert s.git_push_enabled is False
    assert s.entitlements_path == tmp_path / "entitlements.json"
    assert s.violations_path == tmp_path / "violations.json"


def test_settings_requires_bearer_token(monkeypatch, tmp_path):
    monkeypatch.setenv("EQM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("EQM_BEARER_TOKEN", raising=False)
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eqm.config'`

- [ ] **Step 3: Implement `src/eqm/config.py`**

```python
"""Application config loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EQM_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("./data"))
    bearer_token: str
    git_push_enabled: bool = False
    git_push_token: str | None = None
    git_remote_url: str | None = None

    @property
    def entitlements_path(self) -> Path:
        return self.data_dir / "entitlements.json"

    @property
    def hr_employees_path(self) -> Path:
        return self.data_dir / "hr_employees.json"

    @property
    def cmdb_resources_path(self) -> Path:
        return self.data_dir / "cmdb_resources.json"

    @property
    def assignments_path(self) -> Path:
        return self.data_dir / "assignments.json"

    @property
    def violations_path(self) -> Path:
        return self.data_dir / "violations.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/eqm/config.py tests/test_config.py
git commit -m "feat(config): add Settings with EQM_* env vars and data path resolvers"
```

---

## Task 3: Models — enums

**Files:**
- Create: `src/eqm/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing test for enums**

`tests/test_models.py`:
```python
from eqm.models import (
    AccessTier,
    Criticality,
    Division,
    EmployeeStatus,
    RecommendedAction,
    ResourceType,
    Role,
    Severity,
    WorkflowState,
)


def test_access_tier_values():
    assert AccessTier.ADMIN == 1
    assert AccessTier.GENERAL_RO == 4
    assert int(AccessTier.READ_WRITE) == 2


def test_role_values():
    assert {r.value for r in Role} == {
        "developer", "operations", "business_user", "business_analyst", "customer",
    }


def test_division_values():
    assert "cyber_tech" in {d.value for d in Division}
    assert "legal_compliance" in {d.value for d in Division}
    assert len(Division) == 9


def test_workflow_states_complete():
    assert {s.value for s in WorkflowState} == {
        "open", "pending_approval", "approved", "rejected", "manual_repair", "resolved",
    }


def test_recommended_actions_complete():
    assert {a.value for a in RecommendedAction} == {
        "auto_revoke_assignment",
        "update_entitlement_field",
        "route_to_entitlement_owner",
        "route_to_user_manager",
        "route_to_compliance",
    }


def test_severity_levels():
    assert {s.value for s in Severity} == {"low", "medium", "high", "critical"}


def test_criticality_levels():
    assert {c.value for c in Criticality} == {"low", "medium", "high", "critical"}


def test_employee_status():
    assert {s.value for s in EmployeeStatus} == {"active", "on_leave", "terminated"}


def test_resource_types():
    assert {t.value for t in ResourceType} == {
        "application", "share_drive", "website", "database", "api",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement enums in `src/eqm/models.py`**

```python
"""Pydantic models and enums for the Entitlement Quality Monitor."""

from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class AccessTier(IntEnum):
    ADMIN = 1
    READ_WRITE = 2
    ELEVATED_RO = 3
    GENERAL_RO = 4


class Role(StrEnum):
    DEVELOPER = "developer"
    OPERATIONS = "operations"
    BUSINESS_USER = "business_user"
    BUSINESS_ANALYST = "business_analyst"
    CUSTOMER = "customer"


class Division(StrEnum):
    CYBER_TECH = "cyber_tech"
    TECH_DEV = "tech_dev"
    TECH_OPS = "tech_ops"
    BUSINESS_DEV = "business_dev"
    BUSINESS_OPS = "business_ops"
    BUSINESS_SALES = "business_sales"
    LEGAL_COMPLIANCE = "legal_compliance"
    FINANCE = "finance"
    HR = "hr"


class EmployeeStatus(StrEnum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class ResourceType(StrEnum):
    APPLICATION = "application"
    SHARE_DRIVE = "share_drive"
    WEBSITE = "website"
    DATABASE = "database"
    API = "api"


class Criticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecommendedAction(StrEnum):
    AUTO_REVOKE_ASSIGNMENT = "auto_revoke_assignment"
    UPDATE_ENTITLEMENT_FIELD = "update_entitlement_field"
    ROUTE_TO_ENTITLEMENT_OWNER = "route_to_entitlement_owner"
    ROUTE_TO_USER_MANAGER = "route_to_user_manager"
    ROUTE_TO_COMPLIANCE = "route_to_compliance"


class WorkflowState(StrEnum):
    OPEN = "open"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    MANUAL_REPAIR = "manual_repair"
    RESOLVED = "resolved"
```

- [ ] **Step 4: Run test to verify enums pass**

Run: `pytest tests/test_models.py -v`
Expected: PASS for all 9 enum tests.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/models.py tests/test_models.py
git commit -m "feat(models): add enums for tiers, roles, divisions, severity, workflow states"
```

---

## Task 4: Models — entity schemas

**Files:**
- Modify: `src/eqm/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Append entity tests to `tests/test_models.py`**

```python
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from eqm.models import (
    Assignment,
    CMDBResource,
    Entitlement,
    HREmployee,
    RoleHistoryEntry,
    Violation,
)


NOW = datetime.now(timezone.utc)


def test_entitlement_minimal_valid():
    e = Entitlement(
        id="ENT-00001",
        name="Prod DB Admin",
        pbl_description="Grants administrator access to the production customer database.",
        access_tier=1,
        acceptable_roles=["operations"],
        division="tech_ops",
        linked_resource_ids=["RES-00001"],
        sod_tags=[],
        created_at=NOW,
        updated_at=NOW,
    )
    assert e.access_tier == 1
    assert e.id == "ENT-00001"


def test_entitlement_rejects_unknown_role():
    with pytest.raises(ValidationError):
        Entitlement(
            id="ENT-2",
            name="X",
            pbl_description="Some description that is long enough.",
            access_tier=2,
            acceptable_roles=["wizard"],
            division="hr",
            linked_resource_ids=[],
            created_at=NOW,
            updated_at=NOW,
        )


def test_hr_employee_with_history():
    emp = HREmployee(
        id="EMP-00001",
        full_name="Alice Lee",
        email="alice@example.com",
        current_role="operations",
        current_division="tech_ops",
        status="active",
        role_history=[
            RoleHistoryEntry(role="developer", division="tech_dev",
                             started_at=NOW - timedelta(days=400), ended_at=NOW - timedelta(days=60)),
            RoleHistoryEntry(role="operations", division="tech_ops",
                             started_at=NOW - timedelta(days=60), ended_at=None),
        ],
        manager_id=None,
        hired_at=NOW - timedelta(days=400),
        terminated_at=None,
    )
    assert emp.role_history[-1].ended_at is None


def test_cmdb_resource_environment_constraint():
    with pytest.raises(ValidationError):
        CMDBResource(
            id="RES-1", name="x", type="application", criticality="high",
            owner_division="hr", environment="staging-2",
            linked_entitlement_ids=[], description="x",
        )


def test_assignment_active_default_true():
    a = Assignment(
        id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1",
        granted_at=NOW, granted_by="system", last_certified_at=None,
    )
    assert a.active is True


def test_violation_default_state_open():
    v = Violation(
        id="VIO-1", rule_id="ENT-Q-01", rule_name="PBL completeness",
        severity="low", detected_at=NOW,
        target_type="entitlement", target_id="ENT-1",
        explanation="Description too short", evidence={"length": 4},
        recommended_action="update_entitlement_field",
        suggested_fix={"pbl_description": "..."},
    )
    assert v.workflow_state == "open"
    assert v.workflow_history == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -v -k "entitlement_minimal or unknown_role or hr_employee or cmdb_resource or assignment or violation_default"`
Expected: FAIL — entity classes not yet defined.

- [ ] **Step 3: Append entity classes to `src/eqm/models.py`**

```python
class RoleHistoryEntry(BaseModel):
    role: Role
    division: Division
    started_at: datetime
    ended_at: datetime | None = None


class Entitlement(BaseModel):
    id: str
    name: str
    pbl_description: str
    access_tier: AccessTier
    acceptable_roles: list[Role]
    division: Division
    linked_resource_ids: list[str] = Field(default_factory=list)
    sod_tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class HREmployee(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    current_role: Role
    current_division: Division
    status: EmployeeStatus
    role_history: list[RoleHistoryEntry] = Field(default_factory=list)
    manager_id: str | None = None
    hired_at: datetime
    terminated_at: datetime | None = None


class CMDBResource(BaseModel):
    id: str
    name: str
    type: ResourceType
    criticality: Criticality
    owner_division: Division
    environment: Literal["dev", "staging", "prod"]
    linked_entitlement_ids: list[str] = Field(default_factory=list)
    description: str


class Assignment(BaseModel):
    id: str
    employee_id: str
    entitlement_id: str
    granted_at: datetime
    granted_by: str
    last_certified_at: datetime | None = None
    active: bool = True


class WorkflowHistoryEntry(BaseModel):
    from_state: WorkflowState
    to_state: WorkflowState
    actor: str
    timestamp: datetime
    note: str | None = None
    override_fix: dict | None = None


class Violation(BaseModel):
    id: str
    rule_id: str
    rule_name: str
    severity: Severity
    detected_at: datetime
    target_type: Literal["entitlement", "assignment", "employee", "resource"]
    target_id: str
    explanation: str
    evidence: dict
    recommended_action: RecommendedAction
    suggested_fix: dict
    workflow_state: WorkflowState = WorkflowState.OPEN
    workflow_history: list[WorkflowHistoryEntry] = Field(default_factory=list)
    appian_case_id: str | None = None
```

Note: `EmailStr` requires `email-validator`. Add `email-validator>=2.2` to `pyproject.toml` dependencies, then `pip install -e ".[dev]"`.

- [ ] **Step 4: Update pyproject and reinstall**

In `pyproject.toml`, add `"email-validator>=2.2",` to the `dependencies` list, then:
```bash
pip install -e ".[dev]"
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_models.py -v`
Expected: PASS for all tests.

- [ ] **Step 6: Commit**

```bash
git add src/eqm/models.py tests/test_models.py pyproject.toml
git commit -m "feat(models): add Entitlement, HREmployee, CMDBResource, Assignment, Violation"
```

---

## Task 5: Persistence — atomic JSON I/O

**Files:**
- Create: `src/eqm/persistence.py`
- Create: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing test**

`tests/test_persistence.py`:
```python
import asyncio
import json
from pathlib import Path

import pytest

from eqm.persistence import JsonStore


@pytest.fixture
def tmp_store(tmp_path) -> JsonStore:
    return JsonStore(tmp_path)


async def test_write_then_read(tmp_store: JsonStore):
    await tmp_store.write("entitlements.json", [{"id": "ENT-1"}])
    data = await tmp_store.read("entitlements.json")
    assert data == [{"id": "ENT-1"}]


async def test_read_missing_returns_empty(tmp_store: JsonStore):
    assert await tmp_store.read("missing.json") == []


async def test_write_is_atomic(tmp_store: JsonStore, tmp_path):
    await tmp_store.write("x.json", [{"a": 1}])
    # No leftover temp file
    siblings = list(tmp_path.iterdir())
    assert all(p.suffix != ".tmp" for p in siblings)
    # Content is valid JSON, not partial
    raw = (tmp_path / "x.json").read_text()
    assert json.loads(raw) == [{"a": 1}]


async def test_concurrent_writes_serialize(tmp_store: JsonStore):
    async def writer(n):
        await tmp_store.write("c.json", [{"n": n}])
    await asyncio.gather(*(writer(i) for i in range(20)))
    data = await tmp_store.read("c.json")
    assert isinstance(data, list)
    assert len(data) == 1  # last write wins, file is intact
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_persistence.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/persistence.py`**

```python
"""Atomic JSON persistence for the data fabric files."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any


class JsonStore:
    """Atomic, async, per-file-locked JSON store."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, asyncio.Lock] = {}
        self._cache: dict[str, Any] = {}

    def _lock_for(self, name: str) -> asyncio.Lock:
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return self._locks[name]

    async def read(self, name: str) -> list[dict] | dict:
        if name in self._cache:
            return self._cache[name]
        path = self.data_dir / name
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        self._cache[name] = data
        return data

    async def write(self, name: str, data: list[dict] | dict) -> None:
        async with self._lock_for(name):
            path = self.data_dir / name
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str))
            os.replace(tmp, path)
            self._cache[name] = data

    def invalidate(self, name: str | None = None) -> None:
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_persistence.py -v`
Expected: PASS for all 4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/persistence.py tests/test_persistence.py
git commit -m "feat(persistence): atomic JSON store with per-file async locks and in-memory cache"
```

---

## Task 6: Seed data generator

**Files:**
- Create: `src/eqm/seed.py`
- Create: `tests/test_seed.py`

- [ ] **Step 1: Write the failing test**

`tests/test_seed.py`:
```python
from eqm.models import Assignment, CMDBResource, Entitlement, HREmployee
from eqm.seed import SeedConfig, generate_seed


def test_generate_seed_default_counts():
    cfg = SeedConfig(num_entitlements=10, num_employees=20, num_resources=5,
                     num_assignments=30, seed=42)
    bundle = generate_seed(cfg)
    assert len(bundle.entitlements) == 10
    assert len(bundle.hr_employees) == 20
    assert len(bundle.cmdb_resources) == 5
    assert len(bundle.assignments) == 30


def test_generate_seed_is_deterministic():
    cfg = SeedConfig(num_entitlements=5, num_employees=5, num_resources=3,
                     num_assignments=4, seed=123)
    a = generate_seed(cfg)
    b = generate_seed(cfg)
    assert [e.id for e in a.entitlements] == [e.id for e in b.entitlements]
    assert [e.full_name for e in a.hr_employees] == [e.full_name for e in b.hr_employees]


def test_seed_records_are_valid_models():
    cfg = SeedConfig(num_entitlements=3, num_employees=3, num_resources=2,
                     num_assignments=2, seed=1)
    b = generate_seed(cfg)
    for e in b.entitlements:
        assert isinstance(e, Entitlement)
    for emp in b.hr_employees:
        assert isinstance(emp, HREmployee)
    for r in b.cmdb_resources:
        assert isinstance(r, CMDBResource)
    for a in b.assignments:
        assert isinstance(a, Assignment)


def test_seed_assignments_reference_real_entities():
    cfg = SeedConfig(num_entitlements=5, num_employees=5, num_resources=2,
                     num_assignments=10, seed=7)
    b = generate_seed(cfg)
    emp_ids = {e.id for e in b.hr_employees}
    ent_ids = {e.id for e in b.entitlements}
    for a in b.assignments:
        assert a.employee_id in emp_ids
        assert a.entitlement_id in ent_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/seed.py`**

```python
"""Deterministic seed data generation using Faker."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from faker import Faker

from eqm.models import (
    AccessTier,
    Assignment,
    CMDBResource,
    Criticality,
    Division,
    EmployeeStatus,
    Entitlement,
    HREmployee,
    ResourceType,
    Role,
    RoleHistoryEntry,
)

NOW = datetime.now(timezone.utc)
SOD_TAG_PAIRS = [("payment_initiate", "payment_approve"),
                 ("trade_initiate", "trade_settle")]


@dataclass(slots=True)
class SeedConfig:
    num_entitlements: int = 200
    num_employees: int = 500
    num_resources: int = 75
    num_assignments: int = 1200
    seed: int = 42


@dataclass(slots=True)
class SeedBundle:
    entitlements: list[Entitlement]
    hr_employees: list[HREmployee]
    cmdb_resources: list[CMDBResource]
    assignments: list[Assignment]


def _pbl_for(tier: AccessTier, system_name: str) -> str:
    if tier == AccessTier.ADMIN:
        return f"Grants administrator access and full configuration rights to the {system_name} system."
    if tier == AccessTier.READ_WRITE:
        return f"Allows authorized users to read and write business records in {system_name}."
    if tier == AccessTier.ELEVATED_RO:
        return f"Provides elevated read access in {system_name} with limited write capability for approved exceptions."
    return f"Provides general read-only visibility into {system_name} for reporting and review purposes."


def generate_seed(cfg: SeedConfig) -> SeedBundle:
    rnd = random.Random(cfg.seed)
    fake = Faker()
    Faker.seed(cfg.seed)

    resources: list[CMDBResource] = []
    for i in range(cfg.num_resources):
        rt = rnd.choice(list(ResourceType))
        resources.append(CMDBResource(
            id=f"RES-{i+1:05d}",
            name=fake.unique.company() + " " + rt.value.capitalize(),
            type=rt,
            criticality=rnd.choice(list(Criticality)),
            owner_division=rnd.choice(list(Division)),
            environment=rnd.choice(["dev", "staging", "prod"]),
            linked_entitlement_ids=[],
            description=fake.sentence(),
        ))

    entitlements: list[Entitlement] = []
    for i in range(cfg.num_entitlements):
        tier = rnd.choice(list(AccessTier))
        division = rnd.choice(list(Division))
        # Roles allowed at each tier — keep ENT-Q-03 clean for seed data
        if tier == AccessTier.ADMIN:
            allowed = [Role.DEVELOPER, Role.OPERATIONS]
        elif tier == AccessTier.READ_WRITE:
            allowed = [Role.DEVELOPER, Role.OPERATIONS, Role.BUSINESS_ANALYST, Role.BUSINESS_USER]
        else:
            allowed = list(Role)
        roles = rnd.sample(allowed, k=rnd.randint(1, len(allowed)))
        linked = rnd.sample([r.id for r in resources], k=rnd.randint(1, min(3, len(resources))))
        sod = []
        if rnd.random() < 0.05:
            sod.append(rnd.choice([t for pair in SOD_TAG_PAIRS for t in pair]))
        system_name = resources[i % len(resources)].name
        e = Entitlement(
            id=f"ENT-{i+1:05d}",
            name=f"{division.value} {tier.name.lower()} {i+1}",
            pbl_description=_pbl_for(tier, system_name),
            access_tier=tier,
            acceptable_roles=roles,
            division=division,
            linked_resource_ids=linked,
            sod_tags=sod,
            created_at=NOW - timedelta(days=rnd.randint(0, 365)),
            updated_at=NOW,
        )
        entitlements.append(e)
        for rid in linked:
            res = next(r for r in resources if r.id == rid)
            res.linked_entitlement_ids.append(e.id)

    employees: list[HREmployee] = []
    for i in range(cfg.num_employees):
        role = rnd.choice(list(Role))
        division = rnd.choice(list(Division))
        hired_days_ago = rnd.randint(30, 1500)
        hired_at = NOW - timedelta(days=hired_days_ago)
        status = rnd.choices(
            list(EmployeeStatus), weights=[0.92, 0.05, 0.03], k=1)[0]
        history = [RoleHistoryEntry(role=role, division=division,
                                    started_at=hired_at, ended_at=None)]
        terminated_at = NOW - timedelta(days=rnd.randint(1, 60)) if status == EmployeeStatus.TERMINATED else None
        employees.append(HREmployee(
            id=f"EMP-{i+1:05d}",
            full_name=fake.name(),
            email=f"user{i+1:05d}@example.com",
            current_role=role,
            current_division=division,
            status=status,
            role_history=history,
            manager_id=None,
            hired_at=hired_at,
            terminated_at=terminated_at,
        ))

    assignments: list[Assignment] = []
    for i in range(cfg.num_assignments):
        emp = rnd.choice(employees)
        ent = rnd.choice(entitlements)
        assignments.append(Assignment(
            id=f"ASN-{i+1:05d}",
            employee_id=emp.id,
            entitlement_id=ent.id,
            granted_at=NOW - timedelta(days=rnd.randint(0, 365)),
            granted_by="system",
            last_certified_at=NOW - timedelta(days=rnd.randint(0, 180)) if rnd.random() < 0.6 else None,
            active=True,
        ))

    return SeedBundle(entitlements=entitlements, hr_employees=employees,
                      cmdb_resources=resources, assignments=assignments)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_seed.py -v`
Expected: PASS for all 4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/seed.py tests/test_seed.py
git commit -m "feat(seed): deterministic Faker-based seed data generator (200 ents / 500 emps / 75 resources / 1200 assignments)"
```

---

## Task 7: Rule contract + DataSnapshot

**Files:**
- Create: `src/eqm/rules/__init__.py`
- Create: `src/eqm/rules/base.py`
- Create: `tests/rules/__init__.py`
- Create: `tests/rules/conftest.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/conftest.py`:
```python
from datetime import datetime, timezone

import pytest

from eqm.models import (
    AccessTier, Assignment, CMDBResource, Criticality, Division,
    EmployeeStatus, Entitlement, HREmployee, ResourceType, Role,
    RoleHistoryEntry,
)
from eqm.rules.base import DataSnapshot

NOW = datetime.now(timezone.utc)


@pytest.fixture
def empty_snapshot() -> DataSnapshot:
    return DataSnapshot(entitlements=[], hr_employees=[], cmdb_resources=[],
                         assignments=[])


def make_entitlement(**kw) -> Entitlement:
    defaults = dict(
        id="ENT-1", name="Test Entitlement",
        pbl_description="Grants administrator access to the test system for managing configuration.",
        access_tier=AccessTier.ADMIN, acceptable_roles=[Role.OPERATIONS],
        division=Division.TECH_OPS, linked_resource_ids=["RES-1"],
        sod_tags=[], created_at=NOW, updated_at=NOW,
    )
    defaults.update(kw)
    return Entitlement(**defaults)


def make_employee(**kw) -> HREmployee:
    defaults = dict(
        id="EMP-1", full_name="Test User", email="test@example.com",
        current_role=Role.OPERATIONS, current_division=Division.TECH_OPS,
        status=EmployeeStatus.ACTIVE,
        role_history=[RoleHistoryEntry(role=Role.OPERATIONS,
                                       division=Division.TECH_OPS,
                                       started_at=NOW, ended_at=None)],
        manager_id=None, hired_at=NOW, terminated_at=None,
    )
    defaults.update(kw)
    return HREmployee(**defaults)


def make_resource(**kw) -> CMDBResource:
    defaults = dict(
        id="RES-1", name="Test Resource", type=ResourceType.APPLICATION,
        criticality=Criticality.LOW, owner_division=Division.TECH_OPS,
        environment="prod", linked_entitlement_ids=[], description="x",
    )
    defaults.update(kw)
    return CMDBResource(**defaults)


def make_assignment(**kw) -> Assignment:
    defaults = dict(
        id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1",
        granted_at=NOW, granted_by="system", last_certified_at=None,
        active=True,
    )
    defaults.update(kw)
    return Assignment(**defaults)
```

`tests/rules/__init__.py`: (empty)

`tests/test_rules_base.py`:
```python
from eqm.models import RecommendedAction, Severity
from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot, Rule


def test_data_snapshot_is_immutable_lists():
    s = DataSnapshot(entitlements=[], hr_employees=[],
                     cmdb_resources=[], assignments=[])
    assert isinstance(s.entitlements, tuple)
    assert isinstance(s.hr_employees, tuple)


def test_rules_registry_starts_empty():
    # Will be populated by later tasks; the registry exists
    assert isinstance(ALL_RULES, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rules_base.py -v`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement `src/eqm/rules/base.py`**

```python
"""Rule contract and shared snapshot type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

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
```

- [ ] **Step 4: Implement `src/eqm/rules/__init__.py`**

```python
"""Rule registry. Each rule module appends to ALL_RULES on import."""

from eqm.rules.base import DataSnapshot, Rule  # noqa: F401

ALL_RULES: list[Rule] = []
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_rules_base.py tests/rules/ -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/eqm/rules/ tests/rules/ tests/test_rules_base.py
git commit -m "feat(rules): Rule protocol + DataSnapshot + empty registry"
```

---

## Task 8: Rule helper — ID generator and detection time

**Files:**
- Modify: `src/eqm/rules/base.py`
- Create: `tests/test_rules_helpers.py`

- [ ] **Step 1: Write the failing test**

`tests/test_rules_helpers.py`:
```python
from datetime import datetime, timezone

from eqm.rules.base import next_violation_id, now_utc


def test_next_violation_id_increments():
    a = next_violation_id(["VIO-00001", "VIO-00003"])
    assert a == "VIO-00004"


def test_next_violation_id_empty():
    assert next_violation_id([]) == "VIO-00001"


def test_now_utc_returns_aware():
    n = now_utc()
    assert n.tzinfo is not None
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/test_rules_helpers.py -v`
Expected: FAIL — `next_violation_id` not defined.

- [ ] **Step 3: Append helpers to `src/eqm/rules/base.py`**

```python
import re
from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


_VIO_RE = re.compile(r"VIO-(\d+)")


def next_violation_id(existing_ids: list[str]) -> str:
    nums = [int(m.group(1)) for vid in existing_ids if (m := _VIO_RE.match(vid))]
    return f"VIO-{(max(nums) + 1) if nums else 1:05d}"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_rules_helpers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/base.py tests/test_rules_helpers.py
git commit -m "feat(rules): add now_utc() and next_violation_id() helpers"
```

---

## Task 9: Rule ENT-Q-01 — PBL completeness

**Files:**
- Create: `src/eqm/rules/entitlement_quality.py`
- Create: `tests/rules/test_ent_q_01.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_ent_q_01.py`:
```python
from eqm.rules.base import DataSnapshot
from eqm.rules.entitlement_quality import ENT_Q_01

from tests.rules.conftest import make_entitlement


def test_ent_q_01_short_description_fires():
    e = make_entitlement(id="ENT-1", pbl_description="too short")
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_01.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].rule_id == "ENT-Q-01"
    assert violations[0].target_id == "ENT-1"
    assert violations[0].severity == "low"


def test_ent_q_01_banned_phrase_fires():
    e = make_entitlement(id="ENT-2",
                         pbl_description="This entitlement lets you do things in the system.")
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_01.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].target_id == "ENT-2"


def test_ent_q_01_clean_description_passes():
    e = make_entitlement()  # uses default well-formed PBL
    snap = DataSnapshot([e], [], [], [])
    assert ENT_Q_01.evaluate(snap) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/rules/test_ent_q_01.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/rules/entitlement_quality.py`**

```python
"""Entitlement quality rules: ENT-Q-01..04."""

from __future__ import annotations

from eqm.models import (
    AccessTier, RecommendedAction, Severity, Violation, Role, Division,
)
from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc


BANNED_PHRASES = ["access stuff", "do things", "admin access"]


class _ENTQ01:
    id = "ENT-Q-01"
    name = "PBL completeness"
    severity = Severity.LOW
    category = "entitlement_quality"
    recommended_action = RecommendedAction.UPDATE_ENTITLEMENT_FIELD

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for ent in snapshot.entitlements:
            desc = (ent.pbl_description or "").strip().lower()
            reasons: list[str] = []
            if len(desc) < 20:
                reasons.append(f"length={len(desc)} < 20")
            for phrase in BANNED_PHRASES:
                if phrase in desc:
                    reasons.append(f"banned phrase: '{phrase}'")
            if reasons:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=f"PBL description fails completeness check: {'; '.join(reasons)}",
                    evidence={"pbl_description": ent.pbl_description, "reasons": reasons},
                    recommended_action=self.recommended_action,
                    suggested_fix={"pbl_description": "[Owner — please rewrite this description "
                                   "to clearly state what access is granted, on which system, "
                                   "and to whom.]"},
                ))
        return violations


ENT_Q_01 = _ENTQ01()
ALL_RULES.append(ENT_Q_01)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_ent_q_01.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/entitlement_quality.py tests/rules/test_ent_q_01.py
git commit -m "feat(rules): ENT-Q-01 PBL completeness check (length + banned phrases)"
```

---

## Task 10: Rule ENT-Q-02 — PBL template match

**Files:**
- Modify: `src/eqm/rules/entitlement_quality.py`
- Create: `tests/rules/test_ent_q_02.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_ent_q_02.py`:
```python
from eqm.models import AccessTier
from eqm.rules.base import DataSnapshot
from eqm.rules.entitlement_quality import ENT_Q_02

from tests.rules.conftest import make_entitlement


def test_ent_q_02_tier1_missing_administrator_fires():
    e = make_entitlement(
        id="ENT-1", access_tier=AccessTier.ADMIN,
        pbl_description="This entitlement provides access to the production system for users."
    )
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_02.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].target_id == "ENT-1"


def test_ent_q_02_tier4_missing_read_only_fires():
    e = make_entitlement(
        id="ENT-2", access_tier=AccessTier.GENERAL_RO,
        pbl_description="Provides users with general visibility into reporting dashboards."
    )
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_02.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].target_id == "ENT-2"


def test_ent_q_02_tier1_with_administrator_passes():
    e = make_entitlement(
        id="ENT-3", access_tier=AccessTier.ADMIN,
        pbl_description="Grants administrator access to the production billing system."
    )
    assert ENT_Q_02.evaluate(DataSnapshot([e], [], [], [])) == []


def test_ent_q_02_tier2_3_not_evaluated():
    e = make_entitlement(
        id="ENT-4", access_tier=AccessTier.READ_WRITE,
        pbl_description="A short one but no template required for tier 2."
    )
    assert ENT_Q_02.evaluate(DataSnapshot([e], [], [], [])) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_ent_q_02.py -v`
Expected: FAIL — `ENT_Q_02` not defined.

- [ ] **Step 3: Append to `src/eqm/rules/entitlement_quality.py`**

```python
class _ENTQ02:
    id = "ENT-Q-02"
    name = "PBL template match"
    severity = Severity.MEDIUM
    category = "entitlement_quality"
    recommended_action = RecommendedAction.ROUTE_TO_ENTITLEMENT_OWNER

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for ent in snapshot.entitlements:
            desc = (ent.pbl_description or "").lower()
            reason = None
            if ent.access_tier == AccessTier.ADMIN and "administrator" not in desc:
                reason = "Tier-1 PBL must mention 'administrator'"
            elif ent.access_tier == AccessTier.GENERAL_RO and "read-only" not in desc and "read only" not in desc:
                reason = "Tier-4 PBL must mention 'read-only'"
            if reason:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=reason,
                    evidence={"access_tier": int(ent.access_tier),
                              "pbl_description": ent.pbl_description},
                    recommended_action=self.recommended_action,
                    suggested_fix={"pbl_description":
                        f"[Owner — rewrite to match Tier-{int(ent.access_tier)} template "
                        f"({'administrator + system name' if ent.access_tier == AccessTier.ADMIN else 'read-only + system name'}).]"},
                ))
        return violations


ENT_Q_02 = _ENTQ02()
ALL_RULES.append(ENT_Q_02)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_ent_q_02.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/entitlement_quality.py tests/rules/test_ent_q_02.py
git commit -m "feat(rules): ENT-Q-02 PBL template match for Tier-1 and Tier-4"
```

---

## Task 11: Rule ENT-Q-03 — Tier vs role coherence

**Files:**
- Modify: `src/eqm/rules/entitlement_quality.py`
- Create: `tests/rules/test_ent_q_03.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_ent_q_03.py`:
```python
from eqm.models import AccessTier, Role
from eqm.rules.base import DataSnapshot
from eqm.rules.entitlement_quality import ENT_Q_03

from tests.rules.conftest import make_entitlement


def test_tier1_with_customer_fires():
    e = make_entitlement(id="ENT-1", access_tier=AccessTier.ADMIN,
                         acceptable_roles=[Role.OPERATIONS, Role.CUSTOMER])
    violations = ENT_Q_03.evaluate(DataSnapshot([e], [], [], []))
    assert len(violations) == 1


def test_tier1_with_business_user_fires():
    e = make_entitlement(id="ENT-2", access_tier=AccessTier.ADMIN,
                         acceptable_roles=[Role.BUSINESS_USER])
    violations = ENT_Q_03.evaluate(DataSnapshot([e], [], [], []))
    assert len(violations) == 1


def test_tier1_with_developer_passes():
    e = make_entitlement(access_tier=AccessTier.ADMIN,
                         acceptable_roles=[Role.DEVELOPER, Role.OPERATIONS])
    assert ENT_Q_03.evaluate(DataSnapshot([e], [], [], [])) == []


def test_tier2_with_customer_passes():
    e = make_entitlement(access_tier=AccessTier.READ_WRITE,
                         acceptable_roles=[Role.CUSTOMER])
    assert ENT_Q_03.evaluate(DataSnapshot([e], [], [], [])) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_ent_q_03.py -v`
Expected: FAIL — `ENT_Q_03` undefined.

- [ ] **Step 3: Append to `src/eqm/rules/entitlement_quality.py`**

```python
class _ENTQ03:
    id = "ENT-Q-03"
    name = "Tier vs role coherence"
    severity = Severity.HIGH
    category = "entitlement_quality"
    recommended_action = RecommendedAction.UPDATE_ENTITLEMENT_FIELD

    FORBIDDEN_AT_TIER_1 = {Role.CUSTOMER, Role.BUSINESS_USER}

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for ent in snapshot.entitlements:
            if ent.access_tier != AccessTier.ADMIN:
                continue
            forbidden = [r for r in ent.acceptable_roles if r in self.FORBIDDEN_AT_TIER_1]
            if forbidden:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                cleaned = [r for r in ent.acceptable_roles if r not in self.FORBIDDEN_AT_TIER_1]
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=(f"Tier-1 (Admin) entitlement lists forbidden roles: "
                                 f"{[r.value for r in forbidden]}"),
                    evidence={"access_tier": 1,
                              "acceptable_roles": [r.value for r in ent.acceptable_roles],
                              "forbidden_roles": [r.value for r in forbidden]},
                    recommended_action=self.recommended_action,
                    suggested_fix={"acceptable_roles": [r.value for r in cleaned]},
                ))
        return violations


ENT_Q_03 = _ENTQ03()
ALL_RULES.append(ENT_Q_03)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_ent_q_03.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/entitlement_quality.py tests/rules/test_ent_q_03.py
git commit -m "feat(rules): ENT-Q-03 Tier-1 cannot include customer/business_user"
```

---

## Task 12: Rule ENT-Q-04 — Division-resource coherence

**Files:**
- Modify: `src/eqm/rules/entitlement_quality.py`
- Create: `tests/rules/test_ent_q_04.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_ent_q_04.py`:
```python
from eqm.models import AccessTier, Division, Role
from eqm.rules.base import DataSnapshot
from eqm.rules.entitlement_quality import ENT_Q_04

from tests.rules.conftest import make_entitlement, make_resource


def test_hr_division_with_developer_fires():
    e = make_entitlement(id="ENT-1", division=Division.HR,
                         access_tier=AccessTier.READ_WRITE,
                         acceptable_roles=[Role.DEVELOPER, Role.BUSINESS_USER])
    snap = DataSnapshot([e], [], [], [])
    violations = ENT_Q_04.evaluate(snap)
    assert len(violations) == 1
    assert "developer" in violations[0].explanation.lower()


def test_legal_compliance_tier1_on_prod_fires():
    res = make_resource(id="RES-1", environment="prod")
    e = make_entitlement(id="ENT-2", division=Division.LEGAL_COMPLIANCE,
                         access_tier=AccessTier.ADMIN,
                         acceptable_roles=[Role.OPERATIONS],
                         linked_resource_ids=["RES-1"])
    snap = DataSnapshot([e], [], [res], [])
    violations = ENT_Q_04.evaluate(snap)
    assert len(violations) == 1


def test_legal_compliance_tier2_on_prod_passes():
    res = make_resource(id="RES-1", environment="prod")
    e = make_entitlement(division=Division.LEGAL_COMPLIANCE,
                         access_tier=AccessTier.READ_WRITE,
                         linked_resource_ids=["RES-1"])
    assert ENT_Q_04.evaluate(DataSnapshot([e], [], [res], [])) == []


def test_tech_dev_with_developer_passes():
    e = make_entitlement(division=Division.TECH_DEV,
                         acceptable_roles=[Role.DEVELOPER])
    assert ENT_Q_04.evaluate(DataSnapshot([e], [], [], [])) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_ent_q_04.py -v`
Expected: FAIL — `ENT_Q_04` undefined.

- [ ] **Step 3: Append to `src/eqm/rules/entitlement_quality.py`**

```python
class _ENTQ04:
    id = "ENT-Q-04"
    name = "Division-resource coherence"
    severity = Severity.HIGH
    category = "entitlement_quality"
    recommended_action = RecommendedAction.ROUTE_TO_COMPLIANCE

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        violations: list[Violation] = []
        existing_ids: list[str] = []
        resources_by_id = {r.id: r for r in snapshot.cmdb_resources}
        for ent in snapshot.entitlements:
            reason = None
            evidence: dict = {"division": ent.division.value,
                              "access_tier": int(ent.access_tier),
                              "acceptable_roles": [r.value for r in ent.acceptable_roles]}
            if ent.division == Division.HR and Role.DEVELOPER in ent.acceptable_roles:
                reason = "HR division entitlement cannot include 'developer' role"
            elif ent.division == Division.LEGAL_COMPLIANCE and ent.access_tier == AccessTier.ADMIN:
                prod_resources = [resources_by_id[rid].id for rid in ent.linked_resource_ids
                                  if rid in resources_by_id and resources_by_id[rid].environment == "prod"]
                if prod_resources:
                    reason = "Legal/Compliance division cannot have Tier-1 (Admin) on prod resources"
                    evidence["prod_resources"] = prod_resources
            if reason:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=reason, evidence=evidence,
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "review_with_compliance",
                                   "_note": reason},
                ))
        return violations


ENT_Q_04 = _ENTQ04()
ALL_RULES.append(ENT_Q_04)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_ent_q_04.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/entitlement_quality.py tests/rules/test_ent_q_04.py
git commit -m "feat(rules): ENT-Q-04 division-resource coherence (HR no devs; Legal no Tier-1 prod)"
```

---

## Task 13: Rule TOX-01 — Maker-checker conflict

**Files:**
- Create: `src/eqm/rules/toxic_combinations.py`
- Create: `tests/rules/test_tox_01.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_tox_01.py`:
```python
from eqm.rules.base import DataSnapshot
from eqm.rules.toxic_combinations import TOX_01

from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_tox_01_user_holds_initiate_and_approve_fires():
    e1 = make_entitlement(id="ENT-1", sod_tags=["payment_initiate"])
    e2 = make_entitlement(id="ENT-2", sod_tags=["payment_approve"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    a2 = make_assignment(id="ASN-2", employee_id="EMP-1", entitlement_id="ENT-2")
    snap = DataSnapshot([e1, e2], [emp], [], [a1, a2])
    violations = TOX_01.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].severity == "critical"
    assert violations[0].target_id == "EMP-1"
    assert violations[0].target_type == "employee"


def test_tox_01_only_one_side_passes():
    e1 = make_entitlement(id="ENT-1", sod_tags=["payment_initiate"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    snap = DataSnapshot([e1], [emp], [], [a1])
    assert TOX_01.evaluate(snap) == []


def test_tox_01_inactive_assignments_ignored():
    e1 = make_entitlement(id="ENT-1", sod_tags=["payment_initiate"])
    e2 = make_entitlement(id="ENT-2", sod_tags=["payment_approve"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1",
                         entitlement_id="ENT-1", active=False)
    a2 = make_assignment(id="ASN-2", employee_id="EMP-1", entitlement_id="ENT-2")
    snap = DataSnapshot([e1, e2], [emp], [], [a1, a2])
    assert TOX_01.evaluate(snap) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_tox_01.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/rules/toxic_combinations.py`**

```python
"""Toxic combination rules: TOX-01..03."""

from __future__ import annotations

from collections import defaultdict

from eqm.models import AccessTier, RecommendedAction, Role, Severity, Violation
from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc


SOD_PAIRS = [("payment_initiate", "payment_approve"),
             ("trade_initiate", "trade_settle")]


class _TOX01:
    id = "TOX-01"
    name = "Maker-checker conflict"
    severity = Severity.CRITICAL
    category = "toxic_combination"
    recommended_action = RecommendedAction.ROUTE_TO_COMPLIANCE

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        # employee_id -> set of sod_tags they hold via active assignments
        tags_by_emp: dict[str, set[str]] = defaultdict(set)
        ents_by_emp: dict[str, set[str]] = defaultdict(set)
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            if not ent:
                continue
            for tag in ent.sod_tags:
                tags_by_emp[a.employee_id].add(tag)
                ents_by_emp[a.employee_id].add(ent.id)

        violations: list[Violation] = []
        existing_ids: list[str] = []
        for emp_id, tags in tags_by_emp.items():
            for left, right in SOD_PAIRS:
                if left in tags and right in tags:
                    vid = next_violation_id(existing_ids)
                    existing_ids.append(vid)
                    violations.append(Violation(
                        id=vid, rule_id=self.id, rule_name=self.name,
                        severity=self.severity, detected_at=now_utc(),
                        target_type="employee", target_id=emp_id,
                        explanation=(f"Employee holds both '{left}' and '{right}' "
                                     f"entitlements — segregation of duties violation."),
                        evidence={"sod_pair": [left, right],
                                  "entitlement_ids": sorted(ents_by_emp[emp_id])},
                        recommended_action=self.recommended_action,
                        suggested_fix={"_action": "compliance_review",
                                       "_choices": ["revoke_left_side", "revoke_right_side"],
                                       "_pair": [left, right]},
                    ))
        return violations


TOX_01 = _TOX01()
ALL_RULES.append(TOX_01)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_tox_01.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/toxic_combinations.py tests/rules/test_tox_01.py
git commit -m "feat(rules): TOX-01 maker-checker SoD conflict"
```

---

## Task 14: Rule TOX-02 — Dev + Prod-Admin on same application

**Files:**
- Modify: `src/eqm/rules/toxic_combinations.py`
- Create: `tests/rules/test_tox_02.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_tox_02.py`:
```python
from eqm.models import AccessTier, Role
from eqm.rules.base import DataSnapshot
from eqm.rules.toxic_combinations import TOX_02

from tests.rules.conftest import make_assignment, make_employee, make_entitlement, make_resource


def test_tox_02_same_user_dev_admin_and_ops_admin_on_same_resource_fires():
    res = make_resource(id="RES-1", environment="prod")
    e_dev = make_entitlement(id="ENT-DEV", access_tier=AccessTier.ADMIN,
                             acceptable_roles=[Role.DEVELOPER],
                             linked_resource_ids=["RES-1"])
    e_ops = make_entitlement(id="ENT-OPS", access_tier=AccessTier.ADMIN,
                             acceptable_roles=[Role.OPERATIONS],
                             linked_resource_ids=["RES-1"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-DEV")
    a2 = make_assignment(id="ASN-2", employee_id="EMP-1", entitlement_id="ENT-OPS")
    snap = DataSnapshot([e_dev, e_ops], [emp], [res], [a1, a2])
    violations = TOX_02.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].severity == "critical"


def test_tox_02_different_resources_passes():
    r1 = make_resource(id="RES-1", environment="prod")
    r2 = make_resource(id="RES-2", environment="prod")
    e_dev = make_entitlement(id="ENT-DEV", access_tier=AccessTier.ADMIN,
                             acceptable_roles=[Role.DEVELOPER],
                             linked_resource_ids=["RES-1"])
    e_ops = make_entitlement(id="ENT-OPS", access_tier=AccessTier.ADMIN,
                             acceptable_roles=[Role.OPERATIONS],
                             linked_resource_ids=["RES-2"])
    emp = make_employee(id="EMP-1")
    a1 = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-DEV")
    a2 = make_assignment(id="ASN-2", employee_id="EMP-1", entitlement_id="ENT-OPS")
    assert TOX_02.evaluate(DataSnapshot([e_dev, e_ops], [emp], [r1, r2], [a1, a2])) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_tox_02.py -v`
Expected: FAIL — `TOX_02` undefined.

- [ ] **Step 3: Append to `src/eqm/rules/toxic_combinations.py`**

```python
class _TOX02:
    id = "TOX-02"
    name = "Dev + Prod-Admin on same application"
    severity = Severity.CRITICAL
    category = "toxic_combination"
    recommended_action = RecommendedAction.ROUTE_TO_COMPLIANCE

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        # Group active assignments by employee then by linked resource
        # collecting roles seen per (employee, resource).
        per_pair: dict[tuple[str, str], dict[str, set[str]]] = {}
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            if not ent or ent.access_tier != AccessTier.ADMIN:
                continue
            for rid in ent.linked_resource_ids:
                key = (a.employee_id, rid)
                bucket = per_pair.setdefault(key, {"dev": set(), "ops": set()})
                if Role.DEVELOPER in ent.acceptable_roles:
                    bucket["dev"].add(ent.id)
                if Role.OPERATIONS in ent.acceptable_roles:
                    bucket["ops"].add(ent.id)

        violations: list[Violation] = []
        existing_ids: list[str] = []
        for (emp_id, res_id), buckets in per_pair.items():
            if buckets["dev"] and buckets["ops"]:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="employee", target_id=emp_id,
                    explanation=(f"Employee holds both Developer Tier-1 and Operations "
                                 f"Tier-1 access on resource {res_id}."),
                    evidence={"resource_id": res_id,
                              "developer_admin_entitlements": sorted(buckets["dev"]),
                              "operations_admin_entitlements": sorted(buckets["ops"])},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "compliance_review",
                                   "_choices": ["revoke_developer_side", "revoke_operations_side"]},
                ))
        return violations


TOX_02 = _TOX02()
ALL_RULES.append(TOX_02)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_tox_02.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/toxic_combinations.py tests/rules/test_tox_02.py
git commit -m "feat(rules): TOX-02 Dev+Prod-Admin SoD on same application"
```

---

## Task 15: Rule TOX-03 — Tier-1 in 3+ divisions for same user

**Files:**
- Modify: `src/eqm/rules/toxic_combinations.py`
- Create: `tests/rules/test_tox_03.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_tox_03.py`:
```python
from eqm.models import AccessTier, Division
from eqm.rules.base import DataSnapshot
from eqm.rules.toxic_combinations import TOX_03

from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_tox_03_three_divisions_fires():
    ents = [make_entitlement(id=f"ENT-{i}", access_tier=AccessTier.ADMIN, division=d)
            for i, d in enumerate([Division.TECH_OPS, Division.FINANCE, Division.HR])]
    emp = make_employee(id="EMP-1")
    asns = [make_assignment(id=f"ASN-{i}", employee_id="EMP-1",
                            entitlement_id=ents[i].id) for i in range(3)]
    snap = DataSnapshot(ents, [emp], [], asns)
    violations = TOX_03.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].severity == "high"


def test_tox_03_two_divisions_passes():
    ents = [make_entitlement(id=f"ENT-{i}", access_tier=AccessTier.ADMIN, division=d)
            for i, d in enumerate([Division.TECH_OPS, Division.FINANCE])]
    emp = make_employee(id="EMP-1")
    asns = [make_assignment(id=f"ASN-{i}", employee_id="EMP-1",
                            entitlement_id=ents[i].id) for i in range(2)]
    assert TOX_03.evaluate(DataSnapshot(ents, [emp], [], asns)) == []


def test_tox_03_three_divisions_but_not_tier1_passes():
    ents = [make_entitlement(id=f"ENT-{i}", access_tier=AccessTier.READ_WRITE, division=d)
            for i, d in enumerate([Division.TECH_OPS, Division.FINANCE, Division.HR])]
    emp = make_employee(id="EMP-1")
    asns = [make_assignment(id=f"ASN-{i}", employee_id="EMP-1",
                            entitlement_id=ents[i].id) for i in range(3)]
    assert TOX_03.evaluate(DataSnapshot(ents, [emp], [], asns)) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_tox_03.py -v`
Expected: FAIL — `TOX_03` undefined.

- [ ] **Step 3: Append to `src/eqm/rules/toxic_combinations.py`**

```python
class _TOX03:
    id = "TOX-03"
    name = "Tier-1 in 3+ divisions"
    severity = Severity.HIGH
    category = "toxic_combination"
    recommended_action = RecommendedAction.ROUTE_TO_COMPLIANCE

    THRESHOLD = 3

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        divs_by_emp: dict[str, set[str]] = defaultdict(set)
        ent_ids_by_emp: dict[str, set[str]] = defaultdict(set)
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            if not ent or ent.access_tier != AccessTier.ADMIN:
                continue
            divs_by_emp[a.employee_id].add(ent.division.value)
            ent_ids_by_emp[a.employee_id].add(ent.id)

        violations: list[Violation] = []
        existing_ids: list[str] = []
        for emp_id, divs in divs_by_emp.items():
            if len(divs) >= self.THRESHOLD:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="employee", target_id=emp_id,
                    explanation=(f"Employee holds Tier-1 (Admin) in {len(divs)} "
                                 f"divisions: {sorted(divs)}"),
                    evidence={"divisions": sorted(divs),
                              "entitlement_ids": sorted(ent_ids_by_emp[emp_id])},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "compliance_review",
                                   "_note": "Reduce Tier-1 footprint to ≤2 divisions"},
                ))
        return violations


TOX_03 = _TOX03()
ALL_RULES.append(TOX_03)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_tox_03.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/toxic_combinations.py tests/rules/test_tox_03.py
git commit -m "feat(rules): TOX-03 Tier-1 admin spread across 3+ divisions"
```

---

## Task 16: Rule HR-01 — Role mismatch

**Files:**
- Create: `src/eqm/rules/hr_coherence.py`
- Create: `tests/rules/test_hr_01.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_hr_01.py`:
```python
from eqm.models import Role
from eqm.rules.base import DataSnapshot
from eqm.rules.hr_coherence import HR_01

from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_hr_01_role_not_in_acceptable_fires():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.OPERATIONS])
    emp = make_employee(id="EMP-1", current_role=Role.CUSTOMER)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    snap = DataSnapshot([e], [emp], [], [a])
    violations = HR_01.evaluate(snap)
    assert len(violations) == 1
    assert violations[0].target_type == "assignment"
    assert violations[0].target_id == "ASN-1"
    assert violations[0].severity == "medium"
    assert violations[0].suggested_fix == {"_action": "delete_assignment"}


def test_hr_01_role_in_acceptable_passes():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.OPERATIONS, Role.DEVELOPER])
    emp = make_employee(id="EMP-1", current_role=Role.OPERATIONS)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    assert HR_01.evaluate(DataSnapshot([e], [emp], [], [a])) == []


def test_hr_01_inactive_assignment_ignored():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.OPERATIONS])
    emp = make_employee(id="EMP-1", current_role=Role.CUSTOMER)
    a = make_assignment(id="ASN-1", employee_id="EMP-1",
                        entitlement_id="ENT-1", active=False)
    assert HR_01.evaluate(DataSnapshot([e], [emp], [], [a])) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_hr_01.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/rules/hr_coherence.py`**

```python
"""HR coherence rules: HR-01..04."""

from __future__ import annotations

from datetime import timedelta

from eqm.models import EmployeeStatus, RecommendedAction, Severity, Violation
from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc


class _HR01:
    id = "HR-01"
    name = "Role mismatch"
    severity = Severity.MEDIUM
    category = "hr_coherence"
    recommended_action = RecommendedAction.AUTO_REVOKE_ASSIGNMENT

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        emp_by_id = {e.id: e for e in snapshot.hr_employees}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            emp = emp_by_id.get(a.employee_id)
            if not ent or not emp:
                continue
            if emp.current_role not in ent.acceptable_roles:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="assignment", target_id=a.id,
                    explanation=(f"Employee role '{emp.current_role.value}' not in "
                                 f"entitlement.acceptable_roles "
                                 f"{[r.value for r in ent.acceptable_roles]}."),
                    evidence={"employee_id": emp.id,
                              "employee_role": emp.current_role.value,
                              "entitlement_id": ent.id,
                              "acceptable_roles": [r.value for r in ent.acceptable_roles]},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "delete_assignment"},
                ))
        return violations


HR_01 = _HR01()
ALL_RULES.append(HR_01)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_hr_01.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/hr_coherence.py tests/rules/test_hr_01.py
git commit -m "feat(rules): HR-01 role mismatch on active assignments"
```

---

## Task 17: Rule HR-02 — Division mismatch

**Files:**
- Modify: `src/eqm/rules/hr_coherence.py`
- Create: `tests/rules/test_hr_02.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_hr_02.py`:
```python
from eqm.models import Division, Role
from eqm.rules.base import DataSnapshot
from eqm.rules.hr_coherence import HR_02

from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_hr_02_division_mismatch_fires():
    e = make_entitlement(id="ENT-1", division=Division.FINANCE,
                         acceptable_roles=[Role.OPERATIONS])
    emp = make_employee(id="EMP-1", current_division=Division.HR,
                        current_role=Role.OPERATIONS)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    violations = HR_02.evaluate(DataSnapshot([e], [emp], [], [a]))
    assert len(violations) == 1
    assert violations[0].target_id == "ASN-1"
    assert violations[0].severity == "medium"


def test_hr_02_same_division_passes():
    e = make_entitlement(division=Division.HR)
    emp = make_employee(current_division=Division.HR)
    a = make_assignment()
    assert HR_02.evaluate(DataSnapshot([e], [emp], [], [a])) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_hr_02.py -v`
Expected: FAIL — `HR_02` undefined.

- [ ] **Step 3: Append to `src/eqm/rules/hr_coherence.py`**

```python
class _HR02:
    id = "HR-02"
    name = "Division mismatch"
    severity = Severity.MEDIUM
    category = "hr_coherence"
    recommended_action = RecommendedAction.AUTO_REVOKE_ASSIGNMENT

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        emp_by_id = {e.id: e for e in snapshot.hr_employees}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            emp = emp_by_id.get(a.employee_id)
            if not ent or not emp:
                continue
            if emp.current_division != ent.division:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="assignment", target_id=a.id,
                    explanation=(f"Employee division '{emp.current_division.value}' "
                                 f"does not match entitlement division "
                                 f"'{ent.division.value}'."),
                    evidence={"employee_id": emp.id,
                              "employee_division": emp.current_division.value,
                              "entitlement_id": ent.id,
                              "entitlement_division": ent.division.value},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "delete_assignment"},
                ))
        return violations


HR_02 = _HR02()
ALL_RULES.append(HR_02)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_hr_02.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/hr_coherence.py tests/rules/test_hr_02.py
git commit -m "feat(rules): HR-02 division mismatch on active assignments"
```

---

## Task 18: Rule HR-03 — Legacy entitlement (≥30 days post-role-change)

**Files:**
- Modify: `src/eqm/rules/hr_coherence.py`
- Create: `tests/rules/test_hr_03.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_hr_03.py`:
```python
from datetime import timedelta

from freezegun import freeze_time

from eqm.models import Division, Role, RoleHistoryEntry
from eqm.rules.base import DataSnapshot
from eqm.rules.hr_coherence import HR_03

from tests.rules.conftest import NOW, make_assignment, make_employee, make_entitlement


def _emp_with_role_change(days_ago: int):
    return make_employee(
        id="EMP-1",
        current_role=Role.OPERATIONS,
        current_division=Division.TECH_OPS,
        role_history=[
            RoleHistoryEntry(role=Role.DEVELOPER, division=Division.TECH_DEV,
                             started_at=NOW - timedelta(days=400),
                             ended_at=NOW - timedelta(days=days_ago)),
            RoleHistoryEntry(role=Role.OPERATIONS, division=Division.TECH_OPS,
                             started_at=NOW - timedelta(days=days_ago), ended_at=None),
        ],
    )


def test_hr_03_role_change_31d_with_legacy_entitlement_fires():
    # Old role: developer; new role: operations.
    # Entitlement only accepts developer — legacy.
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.DEVELOPER])
    emp = _emp_with_role_change(days_ago=31)
    a = make_assignment(id="ASN-1", employee_id="EMP-1",
                        entitlement_id="ENT-1",
                        granted_at=NOW - timedelta(days=200))
    violations = HR_03.evaluate(DataSnapshot([e], [emp], [], [a]))
    assert len(violations) == 1
    assert violations[0].severity == "high"
    assert violations[0].target_id == "ASN-1"


def test_hr_03_role_change_29d_does_not_fire():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.DEVELOPER])
    emp = _emp_with_role_change(days_ago=29)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    assert HR_03.evaluate(DataSnapshot([e], [emp], [], [a])) == []


def test_hr_03_no_role_change_history_does_not_fire():
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.OPERATIONS])
    emp = make_employee(id="EMP-1", current_role=Role.OPERATIONS)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    assert HR_03.evaluate(DataSnapshot([e], [emp], [], [a])) == []


def test_hr_03_assignment_after_role_change_does_not_fire():
    # Granted AFTER the role change — that's intentional, not legacy.
    e = make_entitlement(id="ENT-1", acceptable_roles=[Role.DEVELOPER])
    emp = _emp_with_role_change(days_ago=60)
    a = make_assignment(id="ASN-1", employee_id="EMP-1",
                        entitlement_id="ENT-1",
                        granted_at=NOW - timedelta(days=10))  # post-change
    assert HR_03.evaluate(DataSnapshot([e], [emp], [], [a])) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_hr_03.py -v`
Expected: FAIL — `HR_03` undefined.

- [ ] **Step 3: Append to `src/eqm/rules/hr_coherence.py`**

```python
LEGACY_DAYS_THRESHOLD = 30


class _HR03:
    id = "HR-03"
    name = "Legacy entitlement after role change"
    severity = Severity.HIGH
    category = "hr_coherence"
    recommended_action = RecommendedAction.ROUTE_TO_USER_MANAGER

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        ent_by_id = {e.id: e for e in snapshot.entitlements}
        emp_by_id = {e.id: e for e in snapshot.hr_employees}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        cutoff = now_utc() - timedelta(days=LEGACY_DAYS_THRESHOLD)
        for a in snapshot.assignments:
            if not a.active:
                continue
            ent = ent_by_id.get(a.entitlement_id)
            emp = emp_by_id.get(a.employee_id)
            if not ent or not emp:
                continue
            # Find the most recent role transition (where ended_at != None and is the latest)
            ended_entries = [h for h in emp.role_history if h.ended_at is not None]
            if not ended_entries:
                continue
            last_change_at = max(h.ended_at for h in ended_entries)
            if last_change_at > cutoff:
                continue  # too recent
            if a.granted_at >= last_change_at:
                continue  # granted after the change — not legacy
            # Was the prior role acceptable but current role isn't?
            if emp.current_role in ent.acceptable_roles:
                continue  # still appropriate
            prior_roles = {h.role for h in ended_entries}
            if not (prior_roles & set(ent.acceptable_roles)):
                continue  # never was appropriate; that's HR-01, not HR-03
            vid = next_violation_id(existing_ids)
            existing_ids.append(vid)
            violations.append(Violation(
                id=vid, rule_id=self.id, rule_name=self.name,
                severity=self.severity, detected_at=now_utc(),
                target_type="assignment", target_id=a.id,
                explanation=(f"Assignment was appropriate under prior role(s) "
                             f"but employee's current role is "
                             f"'{emp.current_role.value}'. Last role change "
                             f"was {last_change_at.isoformat()}."),
                evidence={"employee_id": emp.id,
                          "current_role": emp.current_role.value,
                          "prior_roles": [r.value for r in prior_roles],
                          "last_role_change_at": last_change_at.isoformat(),
                          "granted_at": a.granted_at.isoformat()},
                recommended_action=self.recommended_action,
                suggested_fix={"_action": "delete_assignment",
                               "_note": "Manager should confirm before revocation."},
            ))
        return violations


HR_03 = _HR03()
ALL_RULES.append(HR_03)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_hr_03.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/hr_coherence.py tests/rules/test_hr_03.py
git commit -m "feat(rules): HR-03 legacy entitlement after ≥30d-old role change"
```

---

## Task 19: Rule HR-04 — Terminated user holds active assignment

**Files:**
- Modify: `src/eqm/rules/hr_coherence.py`
- Create: `tests/rules/test_hr_04.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_hr_04.py`:
```python
from eqm.models import EmployeeStatus
from eqm.rules.base import DataSnapshot
from eqm.rules.hr_coherence import HR_04

from tests.rules.conftest import make_assignment, make_employee, make_entitlement


def test_hr_04_terminated_with_active_assignment_fires():
    e = make_entitlement(id="ENT-1")
    emp = make_employee(id="EMP-1", status=EmployeeStatus.TERMINATED)
    a = make_assignment(id="ASN-1", employee_id="EMP-1", entitlement_id="ENT-1")
    violations = HR_04.evaluate(DataSnapshot([e], [emp], [], [a]))
    assert len(violations) == 1
    assert violations[0].severity == "critical"
    assert violations[0].target_id == "ASN-1"


def test_hr_04_active_employee_passes():
    e = make_entitlement()
    emp = make_employee()
    a = make_assignment()
    assert HR_04.evaluate(DataSnapshot([e], [emp], [], [a])) == []


def test_hr_04_terminated_with_inactive_assignment_passes():
    e = make_entitlement()
    emp = make_employee(status=EmployeeStatus.TERMINATED)
    a = make_assignment(active=False)
    assert HR_04.evaluate(DataSnapshot([e], [emp], [], [a])) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_hr_04.py -v`
Expected: FAIL — `HR_04` undefined.

- [ ] **Step 3: Append to `src/eqm/rules/hr_coherence.py`**

```python
class _HR04:
    id = "HR-04"
    name = "Terminated user holds active assignment"
    severity = Severity.CRITICAL
    category = "hr_coherence"
    recommended_action = RecommendedAction.AUTO_REVOKE_ASSIGNMENT

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        emp_by_id = {e.id: e for e in snapshot.hr_employees}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for a in snapshot.assignments:
            if not a.active:
                continue
            emp = emp_by_id.get(a.employee_id)
            if not emp:
                continue
            if emp.status == EmployeeStatus.TERMINATED:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="assignment", target_id=a.id,
                    explanation=(f"Terminated employee {emp.id} ({emp.full_name}) "
                                 f"still holds active assignment {a.id}."),
                    evidence={"employee_id": emp.id,
                              "terminated_at": (emp.terminated_at.isoformat()
                                                if emp.terminated_at else None),
                              "entitlement_id": a.entitlement_id},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "delete_assignment"},
                ))
        return violations


HR_04 = _HR04()
ALL_RULES.append(HR_04)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_hr_04.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/hr_coherence.py tests/rules/test_hr_04.py
git commit -m "feat(rules): HR-04 terminated user holds active assignment (CRITICAL)"
```

---

## Task 20: Rule CMDB-01 — Orphan entitlement

**Files:**
- Create: `src/eqm/rules/cmdb_linkage.py`
- Create: `tests/rules/test_cmdb_01.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_cmdb_01.py`:
```python
from eqm.rules.base import DataSnapshot
from eqm.rules.cmdb_linkage import CMDB_01

from tests.rules.conftest import make_entitlement, make_resource


def test_cmdb_01_orphan_fires():
    e = make_entitlement(id="ENT-1", linked_resource_ids=[])
    violations = CMDB_01.evaluate(DataSnapshot([e], [], [], []))
    assert len(violations) == 1
    assert violations[0].target_id == "ENT-1"
    assert violations[0].severity == "low"


def test_cmdb_01_linked_passes():
    res = make_resource(id="RES-1")
    e = make_entitlement(linked_resource_ids=["RES-1"])
    assert CMDB_01.evaluate(DataSnapshot([e], [], [res], [])) == []


def test_cmdb_01_dangling_link_still_fires():
    # Linked id refers to a resource that does NOT exist — treat as orphan.
    e = make_entitlement(id="ENT-2", linked_resource_ids=["RES-NONEXISTENT"])
    violations = CMDB_01.evaluate(DataSnapshot([e], [], [], []))
    assert len(violations) == 1
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_cmdb_01.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/rules/cmdb_linkage.py`**

```python
"""CMDB linkage rules: CMDB-01..02."""

from __future__ import annotations

from eqm.models import AccessTier, Criticality, RecommendedAction, Severity, Violation
from eqm.rules import ALL_RULES
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc


class _CMDB01:
    id = "CMDB-01"
    name = "Orphan entitlement"
    severity = Severity.LOW
    category = "cmdb_linkage"
    recommended_action = RecommendedAction.ROUTE_TO_ENTITLEMENT_OWNER

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        valid_resource_ids = {r.id for r in snapshot.cmdb_resources}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for ent in snapshot.entitlements:
            valid_links = [rid for rid in ent.linked_resource_ids
                           if rid in valid_resource_ids]
            if not valid_links:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=("Entitlement is not linked to any valid CMDB resource."),
                    evidence={"declared_links": ent.linked_resource_ids,
                              "valid_links": valid_links},
                    recommended_action=self.recommended_action,
                    suggested_fix={"_action": "link_to_resource",
                                   "_note": "Owner should add at least one valid resource id."},
                ))
        return violations


CMDB_01 = _CMDB01()
ALL_RULES.append(CMDB_01)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_cmdb_01.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/cmdb_linkage.py tests/rules/test_cmdb_01.py
git commit -m "feat(rules): CMDB-01 orphan entitlement (no valid CMDB link)"
```

---

## Task 21: Rule CMDB-02 — Tier inconsistency on critical resource

**Files:**
- Modify: `src/eqm/rules/cmdb_linkage.py`
- Create: `tests/rules/test_cmdb_02.py`

- [ ] **Step 1: Write the failing test**

`tests/rules/test_cmdb_02.py`:
```python
from eqm.models import AccessTier, Criticality
from eqm.rules.base import DataSnapshot
from eqm.rules.cmdb_linkage import CMDB_02

from tests.rules.conftest import make_entitlement, make_resource


def test_cmdb_02_tier4_on_high_criticality_fires():
    res = make_resource(id="RES-1", criticality=Criticality.HIGH)
    e = make_entitlement(id="ENT-1", access_tier=AccessTier.GENERAL_RO,
                         linked_resource_ids=["RES-1"])
    violations = CMDB_02.evaluate(DataSnapshot([e], [], [res], []))
    assert len(violations) == 1
    assert violations[0].severity == "high"


def test_cmdb_02_tier3_on_critical_fires():
    res = make_resource(id="RES-1", criticality=Criticality.CRITICAL)
    e = make_entitlement(access_tier=AccessTier.ELEVATED_RO,
                         linked_resource_ids=["RES-1"])
    violations = CMDB_02.evaluate(DataSnapshot([e], [], [res], []))
    assert len(violations) == 1


def test_cmdb_02_tier2_on_high_passes():
    res = make_resource(id="RES-1", criticality=Criticality.HIGH)
    e = make_entitlement(access_tier=AccessTier.READ_WRITE,
                         linked_resource_ids=["RES-1"])
    assert CMDB_02.evaluate(DataSnapshot([e], [], [res], [])) == []


def test_cmdb_02_tier4_on_low_passes():
    res = make_resource(id="RES-1", criticality=Criticality.LOW)
    e = make_entitlement(access_tier=AccessTier.GENERAL_RO,
                         linked_resource_ids=["RES-1"])
    assert CMDB_02.evaluate(DataSnapshot([e], [], [res], [])) == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/rules/test_cmdb_02.py -v`
Expected: FAIL — `CMDB_02` undefined.

- [ ] **Step 3: Append to `src/eqm/rules/cmdb_linkage.py`**

```python
HIGH_CRIT = {Criticality.HIGH, Criticality.CRITICAL}


class _CMDB02:
    id = "CMDB-02"
    name = "Tier inconsistency on critical resource"
    severity = Severity.HIGH
    category = "cmdb_linkage"
    recommended_action = RecommendedAction.ROUTE_TO_ENTITLEMENT_OWNER

    def evaluate(self, snapshot: DataSnapshot) -> list[Violation]:
        res_by_id = {r.id: r for r in snapshot.cmdb_resources}
        violations: list[Violation] = []
        existing_ids: list[str] = []
        for ent in snapshot.entitlements:
            if int(ent.access_tier) <= 2:
                continue  # Tier 1/2 are fine
            offending = []
            for rid in ent.linked_resource_ids:
                res = res_by_id.get(rid)
                if res and res.criticality in HIGH_CRIT:
                    offending.append({"id": res.id, "criticality": res.criticality.value})
            if offending:
                vid = next_violation_id(existing_ids)
                existing_ids.append(vid)
                violations.append(Violation(
                    id=vid, rule_id=self.id, rule_name=self.name,
                    severity=self.severity, detected_at=now_utc(),
                    target_type="entitlement", target_id=ent.id,
                    explanation=(f"Entitlement Tier-{int(ent.access_tier)} "
                                 f"is linked to high/critical resources "
                                 f"requiring Tier ≤ 2."),
                    evidence={"access_tier": int(ent.access_tier),
                              "offending_resources": offending},
                    recommended_action=self.recommended_action,
                    suggested_fix={"access_tier": 2},
                ))
        return violations


CMDB_02 = _CMDB02()
ALL_RULES.append(CMDB_02)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/rules/test_cmdb_02.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/cmdb_linkage.py tests/rules/test_cmdb_02.py
git commit -m "feat(rules): CMDB-02 tier inconsistency on high/critical resources"
```

---

## Task 22: Rule registry import wiring

**Files:**
- Modify: `src/eqm/rules/__init__.py`
- Create: `tests/test_rules_registry.py`

- [ ] **Step 1: Write the failing test**

`tests/test_rules_registry.py`:
```python
from eqm.rules import ALL_RULES, ensure_rules_loaded


def test_all_13_rules_registered():
    ensure_rules_loaded()
    ids = sorted(r.id for r in ALL_RULES)
    assert ids == sorted([
        "ENT-Q-01", "ENT-Q-02", "ENT-Q-03", "ENT-Q-04",
        "TOX-01", "TOX-02", "TOX-03",
        "HR-01", "HR-02", "HR-03", "HR-04",
        "CMDB-01", "CMDB-02",
    ])


def test_no_duplicate_rule_ids():
    ensure_rules_loaded()
    ids = [r.id for r in ALL_RULES]
    assert len(ids) == len(set(ids))
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_rules_registry.py -v`
Expected: FAIL — `ensure_rules_loaded` not defined; rules not auto-imported.

- [ ] **Step 3: Update `src/eqm/rules/__init__.py`**

```python
"""Rule registry. Each rule module appends to ALL_RULES on import."""

from eqm.rules.base import DataSnapshot, Rule  # noqa: F401

ALL_RULES: list[Rule] = []

_LOADED = False


def ensure_rules_loaded() -> None:
    """Import all rule modules so they register themselves into ALL_RULES."""
    global _LOADED
    if _LOADED:
        return
    from eqm.rules import cmdb_linkage, entitlement_quality, hr_coherence, toxic_combinations  # noqa: F401
    _LOADED = True


# Auto-load on package import.
ensure_rules_loaded()
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_rules_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/rules/__init__.py tests/test_rules_registry.py
git commit -m "feat(rules): auto-load all 13 rules into ALL_RULES on package import"
```

---

## Task 23: Engine with reconciliation

**Files:**
- Create: `src/eqm/engine.py`
- Create: `tests/test_engine.py`

- [ ] **Step 1: Write the failing test**

`tests/test_engine.py`:
```python
from datetime import timedelta

from eqm.engine import EngineRunResult, run_engine
from eqm.models import Severity, WorkflowHistoryEntry, WorkflowState
from eqm.rules.base import DataSnapshot

from tests.rules.conftest import (
    NOW, make_assignment, make_employee, make_entitlement, make_resource,
)


def _bad_snapshot() -> DataSnapshot:
    # An entitlement with PBL too short → ENT-Q-01.
    e = make_entitlement(id="ENT-1", pbl_description="x")
    return DataSnapshot([e], [], [], [])


def test_engine_emits_violations_first_run():
    snap = _bad_snapshot()
    result = run_engine(snap, existing_violations=[])
    assert isinstance(result, EngineRunResult)
    assert any(v.rule_id == "ENT-Q-01" for v in result.violations)
    assert all(v.workflow_state == WorkflowState.OPEN for v in result.violations)


def test_engine_preserves_pending_approval_state():
    snap = _bad_snapshot()
    first = run_engine(snap, existing_violations=[])
    v = first.violations[0]
    v.workflow_state = WorkflowState.PENDING_APPROVAL
    second = run_engine(snap, existing_violations=first.violations)
    matching = [x for x in second.violations
                if x.rule_id == v.rule_id and x.target_id == v.target_id]
    assert len(matching) == 1
    assert matching[0].workflow_state == WorkflowState.PENDING_APPROVAL
    assert matching[0].id == v.id  # same ID preserved


def test_engine_marks_resolved_when_no_longer_violating():
    snap_bad = _bad_snapshot()
    first = run_engine(snap_bad, existing_violations=[])
    # Now data drifts — entitlement description fixed.
    e_clean = make_entitlement(
        id="ENT-1",
        pbl_description="Provides administrator access to the production system for ops users."
    )
    snap_clean = DataSnapshot([e_clean], [], [], [])
    # The previous violation was PENDING_APPROVAL.
    first.violations[0].workflow_state = WorkflowState.PENDING_APPROVAL
    second = run_engine(snap_clean, existing_violations=first.violations)
    resolved = [v for v in second.violations
                if v.workflow_state == WorkflowState.RESOLVED]
    assert len(resolved) == 1


def test_engine_suppresses_re_detection_when_rejected():
    snap = _bad_snapshot()
    first = run_engine(snap, existing_violations=[])
    first.violations[0].workflow_state = WorkflowState.REJECTED
    second = run_engine(snap, existing_violations=first.violations)
    new_open = [v for v in second.violations
                if v.workflow_state == WorkflowState.OPEN
                and v.rule_id == "ENT-Q-01"
                and v.target_id == "ENT-1"]
    assert new_open == []
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_engine.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/engine.py`**

```python
"""Run all rules, reconcile against existing violations, return updated set."""

from __future__ import annotations

from dataclasses import dataclass

from eqm.models import Violation, WorkflowHistoryEntry, WorkflowState
from eqm.rules import ALL_RULES, ensure_rules_loaded
from eqm.rules.base import DataSnapshot, next_violation_id, now_utc


@dataclass(slots=True)
class EngineRunResult:
    violations: list[Violation]
    new_count: int
    resolved_count: int
    suppressed_rejected_count: int
    preserved_count: int


def _key(v: Violation) -> tuple[str, str, str]:
    return (v.rule_id, v.target_type, v.target_id)


def run_engine(snapshot: DataSnapshot,
               existing_violations: list[Violation]) -> EngineRunResult:
    ensure_rules_loaded()
    # Collect newly evaluated violations from all rules.
    detected: list[Violation] = []
    for rule in ALL_RULES:
        detected.extend(rule.evaluate(snapshot))

    existing_by_key: dict[tuple[str, str, str], Violation] = {
        _key(v): v for v in existing_violations
    }
    detected_by_key: dict[tuple[str, str, str], Violation] = {
        _key(v): v for v in detected
    }

    out: list[Violation] = []
    new_count = resolved_count = suppressed = preserved = 0

    used_ids = {v.id for v in existing_violations}

    # Pass 1: keep / resolve / suppress existing.
    for key, ev in existing_by_key.items():
        still_violating = key in detected_by_key
        if ev.workflow_state == WorkflowState.REJECTED:
            # Terminal — keep as-is, suppress new detection.
            out.append(ev)
            if still_violating:
                suppressed += 1
            continue
        if ev.workflow_state == WorkflowState.RESOLVED:
            out.append(ev)
            continue
        if still_violating:
            preserved += 1
            out.append(ev)  # preserve workflow_state, evidence, etc.
        else:
            # Auto-resolve.
            ev.workflow_history.append(WorkflowHistoryEntry(
                from_state=ev.workflow_state,
                to_state=WorkflowState.RESOLVED,
                actor="engine", timestamp=now_utc(),
                note="auto-resolved by drift",
            ))
            ev.workflow_state = WorkflowState.RESOLVED
            resolved_count += 1
            out.append(ev)

    # Pass 2: create new violations not present before AND not suppressed by REJECTED.
    suppressed_keys = {k for k, v in existing_by_key.items()
                       if v.workflow_state == WorkflowState.REJECTED}
    for key, det in detected_by_key.items():
        if key in existing_by_key:
            continue
        if key in suppressed_keys:
            continue
        new_id = next_violation_id(list(used_ids))
        used_ids.add(new_id)
        det.id = new_id
        out.append(det)
        new_count += 1

    return EngineRunResult(
        violations=out,
        new_count=new_count,
        resolved_count=resolved_count,
        suppressed_rejected_count=suppressed,
        preserved_count=preserved,
    )
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_engine.py -v`
Expected: PASS for all 4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/engine.py tests/test_engine.py
git commit -m "feat(engine): run_engine with reconciliation (preserve, resolve, suppress-rejected)"
```

---

## Task 24: Workflow state machine

**Files:**
- Create: `src/eqm/workflow.py`
- Create: `tests/test_workflow.py`

- [ ] **Step 1: Write the failing test**

`tests/test_workflow.py`:
```python
import pytest

from eqm.models import Violation, WorkflowState
from eqm.workflow import IllegalTransition, transition

from tests.rules.conftest import NOW


def _v(state: WorkflowState) -> Violation:
    return Violation(
        id="VIO-1", rule_id="ENT-Q-01", rule_name="x",
        severity="low", detected_at=NOW,
        target_type="entitlement", target_id="ENT-1",
        explanation="x", evidence={},
        recommended_action="update_entitlement_field",
        suggested_fix={}, workflow_state=state,
    )


def test_open_to_pending_approval_legal():
    v = _v(WorkflowState.OPEN)
    transition(v, to=WorkflowState.PENDING_APPROVAL, actor="appian", note=None)
    assert v.workflow_state == WorkflowState.PENDING_APPROVAL
    assert len(v.workflow_history) == 1


def test_pending_to_approved_legal():
    v = _v(WorkflowState.PENDING_APPROVAL)
    transition(v, to=WorkflowState.APPROVED, actor="alice@example.com",
               note="approved")
    assert v.workflow_state == WorkflowState.APPROVED


def test_pending_to_rejected_requires_note():
    v = _v(WorkflowState.PENDING_APPROVAL)
    with pytest.raises(IllegalTransition):
        transition(v, to=WorkflowState.REJECTED, actor="x", note=None)
    transition(v, to=WorkflowState.REJECTED, actor="x", note="not a real issue")
    assert v.workflow_state == WorkflowState.REJECTED


def test_open_to_approved_illegal():
    v = _v(WorkflowState.OPEN)
    with pytest.raises(IllegalTransition):
        transition(v, to=WorkflowState.APPROVED, actor="x", note=None)


def test_resolved_terminal():
    v = _v(WorkflowState.RESOLVED)
    with pytest.raises(IllegalTransition):
        transition(v, to=WorkflowState.OPEN, actor="x", note=None)


def test_override_fix_recorded():
    v = _v(WorkflowState.PENDING_APPROVAL)
    transition(v, to=WorkflowState.APPROVED, actor="alice",
               note="modified", override_fix={"pbl_description": "new"})
    assert v.workflow_history[-1].override_fix == {"pbl_description": "new"}
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_workflow.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/workflow.py`**

```python
"""Violation workflow state machine."""

from __future__ import annotations

from datetime import datetime, timezone

from eqm.models import Violation, WorkflowHistoryEntry, WorkflowState


class IllegalTransition(Exception):
    """Raised when a requested workflow transition is not allowed."""

    def __init__(self, current: WorkflowState, to: WorkflowState,
                 legal: list[WorkflowState]) -> None:
        super().__init__(f"Cannot transition {current.value} -> {to.value}. "
                          f"Legal: {[s.value for s in legal]}")
        self.current = current
        self.to = to
        self.legal = legal


LEGAL_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.OPEN: {WorkflowState.PENDING_APPROVAL},
    WorkflowState.PENDING_APPROVAL: {
        WorkflowState.APPROVED,
        WorkflowState.REJECTED,
        WorkflowState.MANUAL_REPAIR,
    },
    WorkflowState.APPROVED: {WorkflowState.RESOLVED},
    WorkflowState.MANUAL_REPAIR: {WorkflowState.RESOLVED},
    WorkflowState.REJECTED: set(),  # terminal
    WorkflowState.RESOLVED: set(),  # terminal
}


def legal_next_states(current: WorkflowState) -> list[WorkflowState]:
    return sorted(LEGAL_TRANSITIONS[current], key=lambda s: s.value)


def transition(violation: Violation, *, to: WorkflowState, actor: str,
               note: str | None, override_fix: dict | None = None) -> None:
    legal = LEGAL_TRANSITIONS[violation.workflow_state]
    if to not in legal:
        raise IllegalTransition(violation.workflow_state, to, sorted(legal, key=lambda s: s.value))
    if to == WorkflowState.REJECTED and not note:
        raise IllegalTransition(violation.workflow_state, to, list(legal))  # rejection requires reason
    entry = WorkflowHistoryEntry(
        from_state=violation.workflow_state, to_state=to, actor=actor,
        timestamp=datetime.now(timezone.utc), note=note, override_fix=override_fix,
    )
    violation.workflow_history.append(entry)
    violation.workflow_state = to
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_workflow.py -v`
Expected: PASS for all 6 tests.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/workflow.py tests/test_workflow.py
git commit -m "feat(workflow): violation state machine with legal transitions and rejected-requires-note"
```

---

## Task 25: Simulator drift mode

**Files:**
- Create: `src/eqm/simulator.py`
- Create: `tests/test_simulator.py`

- [ ] **Step 1: Write the failing test**

`tests/test_simulator.py`:
```python
from eqm.seed import SeedConfig, generate_seed
from eqm.simulator import drift_tick


def test_drift_tick_returns_summary_and_mutates_state():
    bundle = generate_seed(SeedConfig(num_entitlements=20, num_employees=30,
                                      num_resources=5, num_assignments=40, seed=1))
    summary = drift_tick(bundle, tick_number=1)
    assert summary.tick_number == 1
    assert summary.changes
    # At least one mutation happened.
    assert (summary.new_employees + summary.role_changes + summary.terminations
            + summary.new_assignments + summary.new_entitlements) > 0


def test_drift_tick_is_deterministic_with_same_tick_number():
    cfg = SeedConfig(num_entitlements=10, num_employees=10, num_resources=3,
                     num_assignments=10, seed=99)
    a = generate_seed(cfg); b = generate_seed(cfg)
    sa = drift_tick(a, tick_number=42)
    sb = drift_tick(b, tick_number=42)
    assert sa.changes == sb.changes
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_simulator.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/simulator.py`**

```python
"""Drift-mode simulator: random, mostly-realistic mutations seeded by tick number."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from faker import Faker

from eqm.models import (
    AccessTier, Assignment, CMDBResource, Criticality, Division,
    EmployeeStatus, Entitlement, HREmployee, ResourceType, Role,
    RoleHistoryEntry,
)
from eqm.seed import SeedBundle


NOW = lambda: datetime.now(timezone.utc)
BAD_PBL_PHRASES = ["This entitlement gives access stuff for users.",
                   "Lets the user do things in the system.",
                   "admin access for whoever needs it"]


@dataclass(slots=True)
class DriftSummary:
    tick_number: int
    new_employees: int = 0
    role_changes: int = 0
    terminations: int = 0
    new_assignments: int = 0
    new_certifications: int = 0
    new_entitlements: int = 0
    new_resources: int = 0
    tier_changes: int = 0
    changes: list[str] = field(default_factory=list)


def _next_id(prefix: str, items) -> str:
    nums = [int(i.id.split("-")[1]) for i in items if i.id.startswith(prefix)]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:05d}"


def drift_tick(bundle: SeedBundle, tick_number: int) -> DriftSummary:
    rnd = random.Random(tick_number * 1009 + 7)
    fake = Faker()
    Faker.seed(tick_number)
    s = DriftSummary(tick_number=tick_number)
    now = NOW()

    # New employees
    for _ in range(rnd.randint(0, 2)):
        eid = _next_id("EMP", bundle.hr_employees)
        role = rnd.choice(list(Role))
        division = rnd.choice(list(Division))
        bundle.hr_employees.append(HREmployee(
            id=eid, full_name=fake.name(),
            email=f"{eid.lower()}@example.com",
            current_role=role, current_division=division,
            status=EmployeeStatus.ACTIVE,
            role_history=[RoleHistoryEntry(role=role, division=division,
                                           started_at=now, ended_at=None)],
            manager_id=None, hired_at=now, terminated_at=None,
        ))
        s.new_employees += 1
        s.changes.append(f"new employee {eid}")

    # Role change (creates legacy seed for HR-03)
    if rnd.random() < 0.5 and bundle.hr_employees:
        emp = rnd.choice(bundle.hr_employees)
        if emp.status == EmployeeStatus.ACTIVE and emp.role_history[-1].ended_at is None:
            emp.role_history[-1] = RoleHistoryEntry(
                role=emp.role_history[-1].role,
                division=emp.role_history[-1].division,
                started_at=emp.role_history[-1].started_at,
                ended_at=now,
            )
            new_role = rnd.choice([r for r in Role if r != emp.current_role])
            new_div = rnd.choice([d for d in Division if d != emp.current_division])
            emp.role_history.append(RoleHistoryEntry(
                role=new_role, division=new_div, started_at=now, ended_at=None))
            emp.current_role = new_role
            emp.current_division = new_div
            s.role_changes += 1
            s.changes.append(f"role change {emp.id}")

    # Termination (seeds HR-04)
    if rnd.random() < 0.3 and bundle.hr_employees:
        active = [e for e in bundle.hr_employees if e.status == EmployeeStatus.ACTIVE]
        if active:
            emp = rnd.choice(active)
            emp.status = EmployeeStatus.TERMINATED
            emp.terminated_at = now
            s.terminations += 1
            s.changes.append(f"terminated {emp.id}")

    # New assignments
    for _ in range(rnd.randint(1, 3)):
        if not bundle.hr_employees or not bundle.entitlements:
            break
        emp = rnd.choice(bundle.hr_employees)
        ent = rnd.choice(bundle.entitlements)
        # 30% intentionally mismatch
        bundle.assignments.append(Assignment(
            id=_next_id("ASN", bundle.assignments),
            employee_id=emp.id, entitlement_id=ent.id,
            granted_at=now, granted_by="system",
            last_certified_at=None, active=True,
        ))
        s.new_assignments += 1

    # Certifications
    for _ in range(rnd.randint(0, 5)):
        if not bundle.assignments:
            break
        a = rnd.choice(bundle.assignments)
        a.last_certified_at = now
        s.new_certifications += 1

    # New entitlement (sometimes bad PBL)
    if rnd.random() < 0.3:
        eid = _next_id("ENT", bundle.entitlements)
        tier = rnd.choice(list(AccessTier))
        is_bad = rnd.random() < 0.4
        pbl = (rnd.choice(BAD_PBL_PHRASES) if is_bad
               else f"Provides {'administrator' if tier == AccessTier.ADMIN else 'read-only' if tier == AccessTier.GENERAL_RO else 'standard'} "
                    f"access to a system for authorized users.")
        bundle.entitlements.append(Entitlement(
            id=eid, name=f"new entitlement {eid}",
            pbl_description=pbl,
            access_tier=tier,
            acceptable_roles=[rnd.choice(list(Role))],
            division=rnd.choice(list(Division)),
            linked_resource_ids=([rnd.choice(bundle.cmdb_resources).id]
                                 if bundle.cmdb_resources and rnd.random() < 0.7 else []),
            sod_tags=[], created_at=now, updated_at=now,
        ))
        s.new_entitlements += 1
        s.changes.append(f"new entitlement {eid} ({'bad' if is_bad else 'clean'})")

    # New resource (sometimes orphan)
    if rnd.random() < 0.2:
        rid = _next_id("RES", bundle.cmdb_resources)
        bundle.cmdb_resources.append(CMDBResource(
            id=rid, name=fake.company(), type=rnd.choice(list(ResourceType)),
            criticality=rnd.choice(list(Criticality)),
            owner_division=rnd.choice(list(Division)),
            environment=rnd.choice(["dev", "staging", "prod"]),
            linked_entitlement_ids=[], description=fake.sentence(),
        ))
        s.new_resources += 1

    # Tier change
    if rnd.random() < 0.1 and bundle.entitlements:
        ent = rnd.choice(bundle.entitlements)
        ent.access_tier = rnd.choice(list(AccessTier))
        ent.updated_at = now
        s.tier_changes += 1

    return s
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_simulator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/simulator.py tests/test_simulator.py
git commit -m "feat(simulator): drift_tick with new employees, role changes, terminations, assignments, entitlements, resources"
```

---

## Task 26: Scenarios

**Files:**
- Create: `src/eqm/scenarios.py`
- Create: `tests/test_scenarios.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scenarios.py`:
```python
import pytest

from eqm.engine import run_engine
from eqm.rules.base import DataSnapshot
from eqm.scenarios import SCENARIOS, run_scenario
from eqm.seed import SeedConfig, generate_seed


def _bundle():
    return generate_seed(SeedConfig(num_entitlements=50, num_employees=50,
                                     num_resources=10, num_assignments=80, seed=5))


def test_all_seven_scenarios_registered():
    assert set(SCENARIOS.keys()) == {
        "terminated_user_with_admin", "sod_payment_breach",
        "legacy_entitlements_after_promotion", "bad_pbl_batch",
        "tier_role_mismatch", "orphan_entitlements", "kitchen_sink",
    }


@pytest.mark.parametrize("name", [
    "terminated_user_with_admin", "sod_payment_breach",
    "legacy_entitlements_after_promotion", "bad_pbl_batch",
    "tier_role_mismatch", "orphan_entitlements", "kitchen_sink",
])
def test_scenario_produces_expected_violations(name):
    bundle = _bundle()
    run_scenario(name, bundle)
    snap = DataSnapshot(bundle.entitlements, bundle.hr_employees,
                        bundle.cmdb_resources, bundle.assignments)
    result = run_engine(snap, existing_violations=[])
    assert result.new_count > 0


def test_unknown_scenario_raises():
    with pytest.raises(KeyError):
        run_scenario("nope", _bundle())
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_scenarios.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/scenarios.py`**

```python
"""Named demo scenarios that inject specific, deterministic violation sets."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from eqm.models import (
    AccessTier, Assignment, CMDBResource, Criticality, Division,
    EmployeeStatus, Entitlement, HREmployee, ResourceType, Role,
    RoleHistoryEntry,
)
from eqm.seed import SeedBundle


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _next_id(prefix: str, items) -> str:
    nums = [int(i.id.split("-")[1]) for i in items if i.id.startswith(prefix)]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:05d}"


def _scenario_terminated_user_with_admin(b: SeedBundle) -> None:
    now = _now()
    eid = _next_id("EMP", b.hr_employees)
    emp = HREmployee(
        id=eid, full_name="Bob Demo", email=f"{eid.lower()}@example.com",
        current_role=Role.OPERATIONS, current_division=Division.TECH_OPS,
        status=EmployeeStatus.TERMINATED,
        role_history=[RoleHistoryEntry(role=Role.OPERATIONS,
                                       division=Division.TECH_OPS,
                                       started_at=now - timedelta(days=400), ended_at=None)],
        manager_id=None,
        hired_at=now - timedelta(days=400),
        terminated_at=now - timedelta(days=1),
    )
    b.hr_employees.append(emp)
    ent = next((e for e in b.entitlements
                if e.access_tier == AccessTier.ADMIN), b.entitlements[0])
    b.assignments.append(Assignment(
        id=_next_id("ASN", b.assignments),
        employee_id=emp.id, entitlement_id=ent.id,
        granted_at=now - timedelta(days=200), granted_by="system",
        last_certified_at=None, active=True,
    ))


def _scenario_sod_payment_breach(b: SeedBundle) -> None:
    now = _now()
    eid = _next_id("EMP", b.hr_employees)
    emp = HREmployee(
        id=eid, full_name="Eve Demo", email=f"{eid.lower()}@example.com",
        current_role=Role.BUSINESS_USER, current_division=Division.FINANCE,
        status=EmployeeStatus.ACTIVE,
        role_history=[RoleHistoryEntry(role=Role.BUSINESS_USER,
                                       division=Division.FINANCE,
                                       started_at=now - timedelta(days=200), ended_at=None)],
        manager_id=None, hired_at=now - timedelta(days=200), terminated_at=None,
    )
    b.hr_employees.append(emp)
    e_init = Entitlement(
        id=_next_id("ENT", b.entitlements), name="Payments — Initiate",
        pbl_description="Allows users to initiate payment requests in the treasury system.",
        access_tier=AccessTier.READ_WRITE,
        acceptable_roles=[Role.BUSINESS_USER, Role.BUSINESS_ANALYST],
        division=Division.FINANCE,
        linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
        sod_tags=["payment_initiate"], created_at=now, updated_at=now,
    )
    e_appr = Entitlement(
        id=_next_id("ENT", b.entitlements + [e_init]), name="Payments — Approve",
        pbl_description="Allows users to approve initiated payment requests in the treasury system.",
        access_tier=AccessTier.READ_WRITE,
        acceptable_roles=[Role.BUSINESS_USER, Role.BUSINESS_ANALYST],
        division=Division.FINANCE,
        linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
        sod_tags=["payment_approve"], created_at=now, updated_at=now,
    )
    b.entitlements.extend([e_init, e_appr])
    for ent in (e_init, e_appr):
        b.assignments.append(Assignment(
            id=_next_id("ASN", b.assignments),
            employee_id=emp.id, entitlement_id=ent.id,
            granted_at=now - timedelta(days=30), granted_by="system",
            last_certified_at=None, active=True,
        ))


def _scenario_legacy_entitlements_after_promotion(b: SeedBundle) -> None:
    now = _now()
    eid = _next_id("EMP", b.hr_employees)
    emp = HREmployee(
        id=eid, full_name="Carol Demo", email=f"{eid.lower()}@example.com",
        current_role=Role.OPERATIONS, current_division=Division.TECH_OPS,
        status=EmployeeStatus.ACTIVE,
        role_history=[
            RoleHistoryEntry(role=Role.DEVELOPER, division=Division.TECH_DEV,
                             started_at=now - timedelta(days=300),
                             ended_at=now - timedelta(days=45)),
            RoleHistoryEntry(role=Role.OPERATIONS, division=Division.TECH_OPS,
                             started_at=now - timedelta(days=45), ended_at=None),
        ],
        manager_id=None, hired_at=now - timedelta(days=300), terminated_at=None,
    )
    b.hr_employees.append(emp)
    dev_ents = [e for e in b.entitlements if Role.DEVELOPER in e.acceptable_roles
                and Role.OPERATIONS not in e.acceptable_roles][:3]
    if len(dev_ents) < 3:
        # Create them on the fly.
        for i in range(3 - len(dev_ents)):
            dev_ents.append(Entitlement(
                id=_next_id("ENT", b.entitlements + dev_ents),
                name=f"Dev tooling {i}",
                pbl_description="Provides developer access to the engineering build system for code commits.",
                access_tier=AccessTier.READ_WRITE,
                acceptable_roles=[Role.DEVELOPER],
                division=Division.TECH_DEV,
                linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
                sod_tags=[], created_at=now - timedelta(days=200),
                updated_at=now - timedelta(days=200),
            ))
        b.entitlements.extend(dev_ents[-(3 - len([e for e in b.entitlements if e in dev_ents])):])
    for ent in dev_ents:
        b.assignments.append(Assignment(
            id=_next_id("ASN", b.assignments),
            employee_id=emp.id, entitlement_id=ent.id,
            granted_at=now - timedelta(days=200), granted_by="system",
            last_certified_at=None, active=True,
        ))


def _scenario_bad_pbl_batch(b: SeedBundle) -> None:
    now = _now()
    bad_descriptions = ["x", "stuff", "do things", "x", "y",
                        "Provides users with access for reporting purposes.",  # tier-4 missing 'read-only'
                        "Manages production system."]                         # tier-1 missing 'administrator'
    tiers = [AccessTier.READ_WRITE, AccessTier.READ_WRITE, AccessTier.READ_WRITE,
             AccessTier.READ_WRITE, AccessTier.READ_WRITE,
             AccessTier.GENERAL_RO, AccessTier.ADMIN]
    for i, (desc, tier) in enumerate(zip(bad_descriptions, tiers)):
        b.entitlements.append(Entitlement(
            id=_next_id("ENT", b.entitlements),
            name=f"bad-pbl-{i}", pbl_description=desc, access_tier=tier,
            acceptable_roles=[Role.OPERATIONS], division=Division.TECH_OPS,
            linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
            sod_tags=[], created_at=now, updated_at=now,
        ))


def _scenario_tier_role_mismatch(b: SeedBundle) -> None:
    now = _now()
    for roles in [[Role.CUSTOMER], [Role.BUSINESS_USER]]:
        b.entitlements.append(Entitlement(
            id=_next_id("ENT", b.entitlements),
            name="bad-tier1", pbl_description="Grants administrator access to the production system.",
            access_tier=AccessTier.ADMIN, acceptable_roles=roles,
            division=Division.FINANCE,
            linked_resource_ids=[b.cmdb_resources[0].id] if b.cmdb_resources else [],
            sod_tags=[], created_at=now, updated_at=now,
        ))


def _scenario_orphan_entitlements(b: SeedBundle) -> None:
    now = _now()
    for i in range(4):
        b.entitlements.append(Entitlement(
            id=_next_id("ENT", b.entitlements),
            name=f"orphan-{i}",
            pbl_description="Provides standard authorized read access to a system for users.",
            access_tier=AccessTier.READ_WRITE,
            acceptable_roles=[Role.OPERATIONS], division=Division.TECH_OPS,
            linked_resource_ids=[],
            sod_tags=[], created_at=now, updated_at=now,
        ))


def _scenario_kitchen_sink(b: SeedBundle) -> None:
    for fn in (_scenario_terminated_user_with_admin,
               _scenario_sod_payment_breach,
               _scenario_legacy_entitlements_after_promotion,
               _scenario_bad_pbl_batch,
               _scenario_tier_role_mismatch,
               _scenario_orphan_entitlements):
        fn(b)


SCENARIOS: dict[str, Callable[[SeedBundle], None]] = {
    "terminated_user_with_admin": _scenario_terminated_user_with_admin,
    "sod_payment_breach": _scenario_sod_payment_breach,
    "legacy_entitlements_after_promotion": _scenario_legacy_entitlements_after_promotion,
    "bad_pbl_batch": _scenario_bad_pbl_batch,
    "tier_role_mismatch": _scenario_tier_role_mismatch,
    "orphan_entitlements": _scenario_orphan_entitlements,
    "kitchen_sink": _scenario_kitchen_sink,
}


def run_scenario(name: str, bundle: SeedBundle) -> None:
    if name not in SCENARIOS:
        raise KeyError(f"Unknown scenario: {name}. Known: {sorted(SCENARIOS)}")
    SCENARIOS[name](bundle)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_scenarios.py -v`
Expected: PASS for all scenarios.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/scenarios.py tests/test_scenarios.py
git commit -m "feat(scenarios): seven named demo scenarios that produce expected violations"
```

---

## Task 27: CLI entrypoint

**Files:**
- Create: `src/eqm/cli.py`
- Create: `src/eqm/__main__.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import json
import subprocess
import sys
from pathlib import Path


def _run(args, env_overrides):
    env = {**__import__("os").environ, "EQM_BEARER_TOKEN": "t",
           "EQM_GIT_PUSH_ENABLED": "0"}
    env.update(env_overrides)
    return subprocess.run([sys.executable, "-m", "eqm", *args],
                          capture_output=True, text=True, env=env)


def test_cli_seed_creates_files(tmp_path: Path):
    res = _run(["seed", "--small"], {"EQM_DATA_DIR": str(tmp_path)})
    assert res.returncode == 0, res.stderr
    for n in ["entitlements.json", "hr_employees.json", "cmdb_resources.json",
              "assignments.json", "violations.json"]:
        assert (tmp_path / n).exists()
    ents = json.loads((tmp_path / "entitlements.json").read_text())
    assert len(ents) > 0


def test_cli_drift_runs_engine(tmp_path: Path):
    _run(["seed", "--small"], {"EQM_DATA_DIR": str(tmp_path)})
    res = _run(["drift"], {"EQM_DATA_DIR": str(tmp_path)})
    assert res.returncode == 0, res.stderr
    vios = json.loads((tmp_path / "violations.json").read_text())
    assert isinstance(vios, list)
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/cli.py`**

```python
"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import sys

from eqm.config import get_settings
from eqm.engine import run_engine
from eqm.models import (
    Assignment, CMDBResource, Entitlement, HREmployee, Violation,
)
from eqm.persistence import JsonStore
from eqm.rules.base import DataSnapshot
from eqm.scenarios import run_scenario
from eqm.seed import SeedBundle, SeedConfig, generate_seed
from eqm.simulator import drift_tick


def _bundle_from_store(store: JsonStore) -> SeedBundle:
    async def load():
        ents = [Entitlement(**x) for x in await store.read("entitlements.json")]
        emps = [HREmployee(**x) for x in await store.read("hr_employees.json")]
        ress = [CMDBResource(**x) for x in await store.read("cmdb_resources.json")]
        asns = [Assignment(**x) for x in await store.read("assignments.json")]
        return SeedBundle(entitlements=ents, hr_employees=emps,
                          cmdb_resources=ress, assignments=asns)
    return asyncio.run(load())


async def _save_bundle(store: JsonStore, b: SeedBundle, vios: list[Violation]) -> None:
    await store.write("entitlements.json", [e.model_dump(mode="json") for e in b.entitlements])
    await store.write("hr_employees.json", [e.model_dump(mode="json") for e in b.hr_employees])
    await store.write("cmdb_resources.json", [e.model_dump(mode="json") for e in b.cmdb_resources])
    await store.write("assignments.json", [e.model_dump(mode="json") for e in b.assignments])
    await store.write("violations.json", [v.model_dump(mode="json") for v in vios])


def _evaluate_and_save(store: JsonStore, b: SeedBundle) -> int:
    snap = DataSnapshot(b.entitlements, b.hr_employees, b.cmdb_resources, b.assignments)
    existing = [Violation(**x) for x in asyncio.run(store.read("violations.json"))]
    result = run_engine(snap, existing_violations=existing)
    asyncio.run(_save_bundle(store, b, result.violations))
    return result.new_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eqm")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_seed = sub.add_parser("seed")
    p_seed.add_argument("--small", action="store_true", help="50/100/15/200 instead of full")
    sub.add_parser("drift")
    p_scen = sub.add_parser("scenario")
    p_scen.add_argument("name")
    sub.add_parser("evaluate")

    args = parser.parse_args(argv)
    settings = get_settings()
    store = JsonStore(settings.data_dir)

    if args.cmd == "seed":
        cfg = (SeedConfig(num_entitlements=50, num_employees=100,
                          num_resources=15, num_assignments=200, seed=42)
               if args.small else SeedConfig())
        bundle = generate_seed(cfg)
        new_count = _evaluate_and_save(store, bundle)
        print(f"seeded; new violations={new_count}")
        return 0

    if args.cmd == "drift":
        bundle = _bundle_from_store(store)
        # Use timestamp-based tick for variability run-to-run; deterministic per call.
        from datetime import datetime
        tick = int(datetime.now().timestamp()) // 60
        summary = drift_tick(bundle, tick_number=tick)
        new_count = _evaluate_and_save(store, bundle)
        print(f"drift tick={tick} changes={len(summary.changes)} new_violations={new_count}")
        return 0

    if args.cmd == "scenario":
        bundle = _bundle_from_store(store)
        run_scenario(args.name, bundle)
        new_count = _evaluate_and_save(store, bundle)
        print(f"scenario={args.name} new_violations={new_count}")
        return 0

    if args.cmd == "evaluate":
        bundle = _bundle_from_store(store)
        new_count = _evaluate_and_save(store, bundle)
        print(f"evaluated; new_violations={new_count}")
        return 0

    parser.error("no command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

`src/eqm/__main__.py`:
```python
from eqm.cli import main

raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/cli.py src/eqm/__main__.py tests/test_cli.py
git commit -m "feat(cli): seed/drift/scenario/evaluate subcommands with JSON persistence"
```

---

## Task 28: FastAPI app skeleton + auth dependency

**Files:**
- Create: `src/eqm/api.py`
- Create: `tests/conftest.py`
- Create: `tests/test_api_health.py`

- [ ] **Step 1: Write the failing test**

`tests/conftest.py`:
```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eqm.config import Settings, get_settings
from eqm.persistence import JsonStore


@pytest.fixture
def app_client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("EQM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EQM_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("EQM_GIT_PUSH_ENABLED", "0")
    get_settings.cache_clear()  # type: ignore[attr-defined]
    # Seed empty files so reads succeed.
    for n in ["entitlements.json", "hr_employees.json", "cmdb_resources.json",
              "assignments.json", "violations.json"]:
        (tmp_path / n).write_text("[]")
    from eqm.api import app
    return TestClient(app), "test-token"
```

`tests/test_api_health.py`:
```python
def test_health_endpoint(app_client):
    client, _ = app_client
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_protected_endpoint_requires_token(app_client):
    client, _ = app_client
    r = client.post("/simulate/tick")
    assert r.status_code == 401


def test_protected_endpoint_with_token(app_client):
    client, token = app_client
    r = client.post("/simulate/tick", headers={"Authorization": f"Bearer {token}"})
    # Endpoint may return 200 or 422 depending on later wiring;
    # for skeleton we accept any non-401.
    assert r.status_code != 401
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_api_health.py -v`
Expected: FAIL — `eqm.api.app` not defined.

- [ ] **Step 3: Implement `src/eqm/api.py`**

```python
"""FastAPI app — skeleton with auth and health."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from eqm.config import Settings, get_settings
from eqm.persistence import JsonStore

bearer_scheme = HTTPBearer(auto_error=False)
app = FastAPI(title="EQM Utility", version="0.1.0")


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    if credentials is None or credentials.credentials != settings.bearer_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing or invalid bearer token")


def get_store(settings: Settings = Depends(get_settings)) -> JsonStore:
    return JsonStore(settings.data_dir)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/simulate/tick", dependencies=[Depends(require_token)])
def simulate_tick_placeholder() -> dict:
    return {"todo": "wired in Task 32"}
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_api_health.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/api.py tests/conftest.py tests/test_api_health.py
git commit -m "feat(api): FastAPI skeleton with bearer auth dependency and /health"
```

---

## Task 29: API read endpoints

**Files:**
- Modify: `src/eqm/api.py`
- Create: `tests/test_api_reads.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_reads.py`:
```python
import json


def _seed_files(tmp_path):
    (tmp_path / "entitlements.json").write_text(json.dumps([
        {"id": "ENT-1", "name": "x", "pbl_description": "A long enough description here.",
         "access_tier": 2, "acceptable_roles": ["operations"], "division": "tech_ops",
         "linked_resource_ids": [], "sod_tags": [],
         "created_at": "2025-01-01T00:00:00+00:00", "updated_at": "2025-01-01T00:00:00+00:00"}
    ]))
    (tmp_path / "hr_employees.json").write_text(json.dumps([
        {"id": "EMP-1", "full_name": "x", "email": "x@example.com",
         "current_role": "operations", "current_division": "tech_ops",
         "status": "active", "role_history": [],
         "manager_id": None, "hired_at": "2024-01-01T00:00:00+00:00",
         "terminated_at": None}
    ]))
    (tmp_path / "cmdb_resources.json").write_text(json.dumps([
        {"id": "RES-1", "name": "x", "type": "application",
         "criticality": "low", "owner_division": "tech_ops",
         "environment": "prod", "linked_entitlement_ids": [], "description": "x"}
    ]))
    (tmp_path / "assignments.json").write_text(json.dumps([
        {"id": "ASN-1", "employee_id": "EMP-1", "entitlement_id": "ENT-1",
         "granted_at": "2024-06-01T00:00:00+00:00", "granted_by": "system",
         "last_certified_at": None, "active": True}
    ]))
    (tmp_path / "violations.json").write_text("[]")


def test_get_entitlements(app_client, tmp_path, monkeypatch):
    client, _ = app_client
    _seed_files(tmp_path)
    r = client.get("/entitlements")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == "ENT-1"


def test_get_entitlement_by_id_404(app_client, tmp_path):
    client, _ = app_client
    _seed_files(tmp_path)
    assert client.get("/entitlements/MISSING").status_code == 404


def test_get_entitlement_filters(app_client, tmp_path):
    client, _ = app_client
    _seed_files(tmp_path)
    r = client.get("/entitlements?division=hr")
    assert r.status_code == 200
    assert r.json() == []


def test_get_violations_filter_state(app_client, tmp_path):
    client, _ = app_client
    _seed_files(tmp_path)
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "ENT-Q-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-01-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "x", "evidence": {}, "recommended_action": "update_entitlement_field",
         "suggested_fix": {}, "workflow_state": "open", "workflow_history": [],
         "appian_case_id": None}
    ]))
    r = client.get("/violations?state=open")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert client.get("/violations?state=resolved").json() == []


def test_get_hr_and_cmdb(app_client, tmp_path):
    client, _ = app_client
    _seed_files(tmp_path)
    assert client.get("/hr/employees").status_code == 200
    assert client.get("/hr/employees/EMP-1").status_code == 200
    assert client.get("/cmdb/resources").status_code == 200
    assert client.get("/cmdb/resources/RES-1").status_code == 200
    assert client.get("/assignments?employee_id=EMP-1").status_code == 200
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_api_reads.py -v`
Expected: FAIL — endpoints not yet implemented.

- [ ] **Step 3: Append to `src/eqm/api.py`**

```python
from fastapi import Query
from typing import Annotated

from eqm.models import (
    Assignment, CMDBResource, Entitlement, HREmployee, Severity,
    Violation, WorkflowState,
)


async def _read_list(store: JsonStore, name: str) -> list[dict]:
    data = await store.read(name)
    return data if isinstance(data, list) else []


@app.get("/entitlements", response_model=list[Entitlement])
async def get_entitlements(
    division: str | None = None,
    tier: int | None = Query(None, ge=1, le=4),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = 0,
    store: JsonStore = Depends(get_store),
) -> list[Entitlement]:
    raw = await _read_list(store, "entitlements.json")
    items = [Entitlement(**x) for x in raw]
    if division:
        items = [e for e in items if e.division.value == division]
    if tier:
        items = [e for e in items if int(e.access_tier) == tier]
    return items[offset:offset + limit]


@app.get("/entitlements/{ent_id}", response_model=Entitlement)
async def get_entitlement(ent_id: str, store: JsonStore = Depends(get_store)) -> Entitlement:
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
    store: JsonStore = Depends(get_store),
) -> list[HREmployee]:
    raw = await _read_list(store, "hr_employees.json")
    items = [HREmployee(**x) for x in raw]
    if division:
        items = [e for e in items if e.current_division.value == division]
    if role:
        items = [e for e in items if e.current_role.value == role]
    return items[offset:offset + limit]


@app.get("/hr/employees/{emp_id}", response_model=HREmployee)
async def get_employee(emp_id: str, store: JsonStore = Depends(get_store)) -> HREmployee:
    raw = await _read_list(store, "hr_employees.json")
    for x in raw:
        if x.get("id") == emp_id:
            return HREmployee(**x)
    raise HTTPException(404, "Employee not found")


@app.get("/cmdb/resources", response_model=list[CMDBResource])
async def get_resources(
    criticality: str | None = None,
    environment: str | None = None,
    store: JsonStore = Depends(get_store),
) -> list[CMDBResource]:
    raw = await _read_list(store, "cmdb_resources.json")
    items = [CMDBResource(**x) for x in raw]
    if criticality:
        items = [r for r in items if r.criticality.value == criticality]
    if environment:
        items = [r for r in items if r.environment == environment]
    return items


@app.get("/cmdb/resources/{res_id}", response_model=CMDBResource)
async def get_resource(res_id: str, store: JsonStore = Depends(get_store)) -> CMDBResource:
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
    store: JsonStore = Depends(get_store),
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
    store: JsonStore = Depends(get_store),
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
async def get_violation(vid: str, store: JsonStore = Depends(get_store)) -> Violation:
    raw = await _read_list(store, "violations.json")
    for x in raw:
        if x.get("id") == vid:
            return Violation(**x)
    raise HTTPException(404, "Violation not found")
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_api_reads.py -v`
Expected: PASS for all 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/api.py tests/test_api_reads.py
git commit -m "feat(api): GET endpoints for entitlements, HR, CMDB, assignments, violations with filters"
```

---

## Task 30: API write endpoints (PATCH/DELETE)

**Files:**
- Modify: `src/eqm/api.py`
- Create: `tests/test_api_writes.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_writes.py`:
```python
import json


def _seed(tmp_path):
    (tmp_path / "entitlements.json").write_text(json.dumps([
        {"id": "ENT-1", "name": "old", "pbl_description": "Long enough description here for tests.",
         "access_tier": 2, "acceptable_roles": ["operations"], "division": "tech_ops",
         "linked_resource_ids": [], "sod_tags": [],
         "created_at": "2025-01-01T00:00:00+00:00", "updated_at": "2025-01-01T00:00:00+00:00"}
    ]))
    (tmp_path / "assignments.json").write_text(json.dumps([
        {"id": "ASN-1", "employee_id": "EMP-1", "entitlement_id": "ENT-1",
         "granted_at": "2024-06-01T00:00:00+00:00", "granted_by": "system",
         "last_certified_at": None, "active": True}
    ]))
    for n in ["hr_employees.json", "cmdb_resources.json", "violations.json"]:
        (tmp_path / n).write_text("[]")


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


def test_patch_entitlement(app_client, tmp_path):
    client, token = app_client
    _seed(tmp_path)
    r = client.patch("/entitlements/ENT-1", json={"name": "new"}, headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["name"] == "new"
    saved = json.loads((tmp_path / "entitlements.json").read_text())
    assert saved[0]["name"] == "new"


def test_patch_entitlement_unknown_field_rejected(app_client, tmp_path):
    client, token = app_client
    _seed(tmp_path)
    r = client.patch("/entitlements/ENT-1", json={"not_a_field": 1}, headers=_hdrs(token))
    assert r.status_code == 400


def test_patch_entitlement_requires_auth(app_client, tmp_path):
    client, _ = app_client
    _seed(tmp_path)
    r = client.patch("/entitlements/ENT-1", json={"name": "x"})
    assert r.status_code == 401


def test_delete_assignment(app_client, tmp_path):
    client, token = app_client
    _seed(tmp_path)
    r = client.delete("/assignments/ASN-1", headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json() == {"id": "ASN-1", "active": False}
    saved = json.loads((tmp_path / "assignments.json").read_text())
    assert saved[0]["active"] is False
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_api_writes.py -v`
Expected: FAIL — endpoints not implemented.

- [ ] **Step 3: Append to `src/eqm/api.py`**

```python
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
            from datetime import datetime, timezone
            if "updated_at" in model.model_fields:
                x["updated_at"] = datetime.now(timezone.utc).isoformat()
            validated = model(**x).model_dump(mode="json")
            raw[i] = validated
            await store.write(name, raw)
            return validated
    raise HTTPException(404, "Not found")


@app.patch("/entitlements/{ent_id}", response_model=Entitlement,
            dependencies=[Depends(require_token)])
async def patch_entitlement(ent_id: str, patch: dict,
                             store: JsonStore = Depends(get_store)) -> Entitlement:
    return Entitlement(**await _patch_record(
        store, "entitlements.json", ent_id, patch,
        ENTITLEMENT_PATCHABLE, Entitlement))


@app.patch("/hr/employees/{emp_id}", response_model=HREmployee,
            dependencies=[Depends(require_token)])
async def patch_employee(emp_id: str, patch: dict,
                          store: JsonStore = Depends(get_store)) -> HREmployee:
    return HREmployee(**await _patch_record(
        store, "hr_employees.json", emp_id, patch,
        EMPLOYEE_PATCHABLE, HREmployee))


@app.patch("/cmdb/resources/{res_id}", response_model=CMDBResource,
            dependencies=[Depends(require_token)])
async def patch_resource(res_id: str, patch: dict,
                          store: JsonStore = Depends(get_store)) -> CMDBResource:
    return CMDBResource(**await _patch_record(
        store, "cmdb_resources.json", res_id, patch,
        RESOURCE_PATCHABLE, CMDBResource))


@app.delete("/assignments/{asn_id}", dependencies=[Depends(require_token)])
async def revoke_assignment(asn_id: str,
                             store: JsonStore = Depends(get_store)) -> dict:
    raw = await _read_list(store, "assignments.json")
    for i, x in enumerate(raw):
        if x.get("id") == asn_id:
            x["active"] = False
            raw[i] = x
            await store.write("assignments.json", raw)
            return {"id": asn_id, "active": False}
    raise HTTPException(404, "Assignment not found")
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_api_writes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/api.py tests/test_api_writes.py
git commit -m "feat(api): PATCH for entitlements/employees/resources, DELETE for assignments (sets active=false)"
```

---

## Task 31: Workflow transition endpoint + reopen

**Files:**
- Modify: `src/eqm/api.py`
- Create: `tests/test_api_transitions.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_transitions.py`:
```python
import json


def _seed_violation(tmp_path, state="open"):
    (tmp_path / "violations.json").write_text(json.dumps([
        {"id": "VIO-1", "rule_id": "ENT-Q-01", "rule_name": "x",
         "severity": "low", "detected_at": "2026-01-01T00:00:00+00:00",
         "target_type": "entitlement", "target_id": "ENT-1",
         "explanation": "x", "evidence": {},
         "recommended_action": "update_entitlement_field",
         "suggested_fix": {"pbl_description": "fixed"},
         "workflow_state": state, "workflow_history": [],
         "appian_case_id": None}
    ]))
    for n in ["entitlements.json", "hr_employees.json",
              "cmdb_resources.json", "assignments.json"]:
        (tmp_path / n).write_text("[]")


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


def test_transition_open_to_pending(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "open")
    r = client.post("/violations/VIO-1/transition",
                    json={"to_state": "pending_approval", "actor": "appian"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["workflow_state"] == "pending_approval"


def test_illegal_transition_returns_409(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "open")
    r = client.post("/violations/VIO-1/transition",
                    json={"to_state": "approved", "actor": "x"},
                    headers=_hdrs(token))
    assert r.status_code == 409
    assert "legal" in r.json()["detail"]


def test_reject_requires_note(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "pending_approval")
    r = client.post("/violations/VIO-1/transition",
                    json={"to_state": "rejected", "actor": "alice"},
                    headers=_hdrs(token))
    assert r.status_code == 400


def test_approved_to_resolved_path(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "pending_approval")
    client.post("/violations/VIO-1/transition",
                json={"to_state": "approved", "actor": "alice", "note": "ok"},
                headers=_hdrs(token))
    r = client.post("/violations/VIO-1/transition",
                    json={"to_state": "resolved", "actor": "system"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["workflow_state"] == "resolved"


def test_reopen_rejected(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "rejected")
    r = client.post("/violations/VIO-1/reopen",
                    json={"actor": "compliance",
                          "note": "circumstances changed"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["workflow_state"] == "open"


def test_reopen_only_for_rejected(app_client, tmp_path):
    client, token = app_client
    _seed_violation(tmp_path, "open")
    r = client.post("/violations/VIO-1/reopen",
                    json={"actor": "x", "note": "x"},
                    headers=_hdrs(token))
    assert r.status_code == 409
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_api_transitions.py -v`
Expected: FAIL — endpoints not implemented.

- [ ] **Step 3: Append to `src/eqm/api.py`**

```python
from pydantic import BaseModel

from eqm.workflow import IllegalTransition, transition


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
                               store: JsonStore = Depends(get_store)) -> Violation:
    raw = await _read_list(store, "violations.json")
    for i, x in enumerate(raw):
        if x.get("id") == vid:
            v = Violation(**x)
            try:
                transition(v, to=body.to_state, actor=body.actor,
                           note=body.note, override_fix=body.override_fix)
            except IllegalTransition as e:
                # Disambiguate: missing note vs disallowed transition.
                from eqm.workflow import LEGAL_TRANSITIONS
                if (body.to_state in LEGAL_TRANSITIONS[v.workflow_state]
                    and body.to_state == WorkflowState.REJECTED
                    and not body.note):
                    raise HTTPException(400, "Rejection requires a note")
                raise HTTPException(409, str(e))
            raw[i] = v.model_dump(mode="json")
            await store.write("violations.json", raw)
            return v
    raise HTTPException(404, "Violation not found")


@app.post("/violations/{vid}/reopen", response_model=Violation,
          dependencies=[Depends(require_token)])
async def violation_reopen(vid: str, body: ReopenRequest,
                            store: JsonStore = Depends(get_store)) -> Violation:
    from datetime import datetime, timezone
    raw = await _read_list(store, "violations.json")
    for i, x in enumerate(raw):
        if x.get("id") == vid:
            v = Violation(**x)
            if v.workflow_state != WorkflowState.REJECTED:
                raise HTTPException(409,
                    f"Reopen only valid from REJECTED; current={v.workflow_state.value}")
            from eqm.models import WorkflowHistoryEntry
            v.workflow_history.append(WorkflowHistoryEntry(
                from_state=WorkflowState.REJECTED, to_state=WorkflowState.OPEN,
                actor=body.actor, timestamp=datetime.now(timezone.utc),
                note=body.note,
            ))
            v.workflow_state = WorkflowState.OPEN
            raw[i] = v.model_dump(mode="json")
            await store.write("violations.json", raw)
            return v
    raise HTTPException(404, "Violation not found")
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_api_transitions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/api.py tests/test_api_transitions.py
git commit -m "feat(api): violation transition state machine + reopen for rejected"
```

---

## Task 32: API simulator + sync endpoints

**Files:**
- Modify: `src/eqm/api.py`
- Create: `tests/test_api_simulate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_simulate.py`:
```python
import json


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


def test_simulate_reset_creates_seed(app_client, tmp_path):
    client, token = app_client
    r = client.post("/simulate/reset", headers=_hdrs(token), json={"small": True})
    assert r.status_code == 200
    body = r.json()
    assert "entitlements" in body
    ents = json.loads((tmp_path / "entitlements.json").read_text())
    assert len(ents) > 0


def test_simulate_tick_runs_drift(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", headers=_hdrs(token), json={"small": True})
    r = client.post("/simulate/tick", headers=_hdrs(token))
    assert r.status_code == 200
    assert "tick_number" in r.json()


def test_simulate_scenario(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", headers=_hdrs(token), json={"small": True})
    r = client.post("/simulate/scenario",
                    json={"name": "terminated_user_with_admin"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["new_violations"] >= 1


def test_simulate_unknown_scenario(app_client):
    client, token = app_client
    client.post("/simulate/reset", headers=_hdrs(token), json={"small": True})
    r = client.post("/simulate/scenario", json={"name": "nope"},
                    headers=_hdrs(token))
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_api_simulate.py -v`
Expected: FAIL — endpoints incomplete.

- [ ] **Step 3: Replace placeholder + add new endpoints in `src/eqm/api.py`**

First, delete the placeholder `simulate_tick_placeholder` function. Then append:

```python
from datetime import datetime

from eqm.engine import run_engine
from eqm.models import Assignment as _Assignment, CMDBResource as _CMDBResource, Entitlement as _Entitlement, HREmployee as _HREmployee
from eqm.rules.base import DataSnapshot
from eqm.scenarios import run_scenario, SCENARIOS
from eqm.seed import SeedBundle, SeedConfig, generate_seed
from eqm.simulator import drift_tick


class ResetRequest(BaseModel):
    small: bool = False


class ScenarioRequest(BaseModel):
    name: str


async def _load_bundle(store: JsonStore) -> SeedBundle:
    return SeedBundle(
        entitlements=[_Entitlement(**x) for x in await _read_list(store, "entitlements.json")],
        hr_employees=[_HREmployee(**x) for x in await _read_list(store, "hr_employees.json")],
        cmdb_resources=[_CMDBResource(**x) for x in await _read_list(store, "cmdb_resources.json")],
        assignments=[_Assignment(**x) for x in await _read_list(store, "assignments.json")],
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
                          store: JsonStore = Depends(get_store)) -> dict:
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
async def simulate_tick(store: JsonStore = Depends(get_store)) -> dict:
    bundle = await _load_bundle(store)
    tick = int(datetime.utcnow().timestamp()) // 60
    summary = drift_tick(bundle, tick_number=tick)
    new_count = await _save_bundle_and_evaluate(store, bundle)
    return {"tick_number": tick, "changes": summary.changes,
            "new_violations": new_count}


@app.post("/simulate/scenario", dependencies=[Depends(require_token)])
async def simulate_scenario(body: ScenarioRequest,
                             store: JsonStore = Depends(get_store)) -> dict:
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
```

Also update `tests/test_api_health.py` `test_protected_endpoint_with_token` — the `/simulate/tick` endpoint will now need an existing seed; expect 404 or 200. Replace with a simpler check:
```python
def test_protected_endpoint_with_token(app_client):
    client, token = app_client
    r = client.post("/simulate/reset", json={"small": True},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_api_simulate.py tests/test_api_health.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/eqm/api.py tests/test_api_simulate.py tests/test_api_health.py
git commit -m "feat(api): /simulate/{reset,tick,scenario} + /sync/{push,pull}-now stubs"
```

---

## Task 33: Dashboard — base layout + overview tab

**Files:**
- Create: `src/eqm/dashboard/__init__.py`
- Create: `src/eqm/dashboard/templates/base.html`
- Create: `src/eqm/dashboard/templates/_control_bar.html`
- Create: `src/eqm/dashboard/templates/overview.html`
- Create: `src/eqm/dashboard/static/style.css`
- Modify: `src/eqm/api.py`
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test**

`tests/test_dashboard.py`:
```python
import json


def test_dashboard_root(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "EQM" in body
    assert "Overview" in body
    # Demo control bar present
    assert "Inject scenario" in body or "scenario" in body.lower()
    # Counts visible
    assert "Entitlements" in body


def test_dashboard_static_css(app_client):
    client, _ = app_client
    r = client.get("/static/style.css")
    assert r.status_code == 200
    assert "body" in r.text.lower()
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_dashboard.py -v`
Expected: FAIL — `/` and `/static/*` not mounted.

- [ ] **Step 3: Implement dashboard package**

`src/eqm/dashboard/__init__.py`:
```python
from pathlib import Path

DASHBOARD_DIR = Path(__file__).parent
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"
```

`src/eqm/dashboard/templates/base.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>EQM — Entitlement Quality Monitor</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header>
    <h1>EQM Utility</h1>
    <nav>
      <a href="/">Overview</a>
      <a href="/dashboard/entitlements">Entitlements</a>
      <a href="/dashboard/hr">HR</a>
      <a href="/dashboard/cmdb">CMDB</a>
      <a href="/dashboard/violations">Violations</a>
    </nav>
  </header>
  {% include "_control_bar.html" %}
  <main>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

`src/eqm/dashboard/templates/_control_bar.html`:
```html
<section class="control-bar">
  <form method="post" action="/dashboard/actions/tick">
    <button type="submit">Run drift tick</button>
  </form>
  <form method="post" action="/dashboard/actions/scenario">
    <select name="name">
      {% for s in scenarios %}<option value="{{ s }}">{{ s }}</option>{% endfor %}
    </select>
    <button type="submit">Inject scenario</button>
  </form>
  <form method="post" action="/dashboard/actions/reset"
        onsubmit="return confirm('Reset to seed? All data + violations will be wiped.')">
    <button type="submit" class="danger">Reset to seed</button>
  </form>
</section>
```

`src/eqm/dashboard/templates/overview.html`:
```html
{% extends "base.html" %}
{% block content %}
<h2>Overview</h2>
<div class="cards">
  <div class="card"><h3>Entitlements</h3><p class="big">{{ counts.entitlements }}</p></div>
  <div class="card"><h3>HR Employees</h3><p class="big">{{ counts.hr_employees }}</p></div>
  <div class="card"><h3>CMDB Resources</h3><p class="big">{{ counts.cmdb_resources }}</p></div>
  <div class="card"><h3>Assignments</h3><p class="big">{{ counts.assignments }}</p></div>
</div>
<h3>Open violations by severity</h3>
<table class="severity">
  <tr><th>Severity</th><th>Open</th><th>Pending Approval</th><th>Resolved</th></tr>
  {% for sev in ["critical", "high", "medium", "low"] %}
  <tr class="sev-{{ sev }}">
    <td>{{ sev }}</td>
    <td>{{ violations_by[sev]["open"] }}</td>
    <td>{{ violations_by[sev]["pending_approval"] }}</td>
    <td>{{ violations_by[sev]["resolved"] }}</td>
  </tr>
  {% endfor %}
</table>
{% endblock %}
```

`src/eqm/dashboard/static/style.css`:
```css
body { font-family: -apple-system, system-ui, sans-serif; margin: 0; background: #f7f8fa; color: #222; }
header { background: #1c2530; color: #fff; padding: 1rem 2rem; display: flex; align-items: baseline; gap: 2rem; }
header h1 { margin: 0; font-size: 1.4rem; }
header nav a { color: #b0c0d0; margin-right: 1rem; text-decoration: none; }
header nav a:hover { color: #fff; }
.control-bar { background: #fff; padding: 0.75rem 2rem; border-bottom: 1px solid #ddd;
                display: flex; gap: 1rem; align-items: center; }
.control-bar form { display: inline-flex; gap: 0.5rem; align-items: center; margin: 0; }
.control-bar button.danger { background: #c33; color: #fff; }
main { padding: 2rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; }
.card { background: #fff; padding: 1rem; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.card .big { font-size: 2rem; margin: 0.25rem 0 0; }
table { border-collapse: collapse; width: 100%; background: #fff; }
table th, table td { padding: 0.5rem 0.75rem; border-bottom: 1px solid #eee; text-align: left; }
.sev-critical td:first-child { color: #b00; font-weight: 600; }
.sev-high td:first-child { color: #c60; font-weight: 600; }
.sev-medium td:first-child { color: #a80; }
.sev-low td:first-child { color: #555; }
```

- [ ] **Step 4: Mount dashboard in `src/eqm/api.py`**

Append:
```python
from collections import defaultdict
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from eqm.dashboard import STATIC_DIR, TEMPLATES_DIR
from eqm.scenarios import SCENARIOS as _ALL_SCENARIOS

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _scenarios_list() -> list[str]:
    return sorted(_ALL_SCENARIOS.keys())


@app.get("/", response_class=HTMLResponse)
async def dashboard_overview(request: Request,
                              store: JsonStore = Depends(get_store)) -> HTMLResponse:
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
async def dashboard_action_tick(store: JsonStore = Depends(get_store)) -> RedirectResponse:
    bundle = await _load_bundle(store)
    tick = int(datetime.utcnow().timestamp()) // 60
    drift_tick(bundle, tick_number=tick)
    await _save_bundle_and_evaluate(store, bundle)
    return RedirectResponse("/", status_code=303)


@app.post("/dashboard/actions/scenario")
async def dashboard_action_scenario(name: Annotated[str, Form()],
                                      store: JsonStore = Depends(get_store)) -> RedirectResponse:
    if name not in SCENARIOS:
        raise HTTPException(400, "Unknown scenario")
    bundle = await _load_bundle(store)
    run_scenario(name, bundle)
    await _save_bundle_and_evaluate(store, bundle)
    return RedirectResponse("/", status_code=303)


@app.post("/dashboard/actions/reset")
async def dashboard_action_reset(store: JsonStore = Depends(get_store)) -> RedirectResponse:
    bundle = generate_seed(SeedConfig(num_entitlements=50, num_employees=100,
                                        num_resources=15, num_assignments=200, seed=42))
    await _save_bundle_and_evaluate(store, bundle)
    return RedirectResponse("/", status_code=303)
```

Add the imports at the top: `from fastapi import Form` (alongside existing `Depends`).

Note: dashboard action endpoints intentionally do NOT require the bearer token — they're driven from a browser session by the demo operator. The presence of these endpoints is acceptable because all data is dummy. If you want auth on dashboard actions, add the same `dependencies=[Depends(require_token)]` later.

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_dashboard.py -v`
Expected: PASS for both tests.

- [ ] **Step 6: Commit**

```bash
git add src/eqm/dashboard/ src/eqm/api.py tests/test_dashboard.py
git commit -m "feat(dashboard): base layout + overview tab + control bar (tick/scenario/reset)"
```

---

## Task 34: Dashboard — entitlements / HR / CMDB tabs

**Files:**
- Create: `src/eqm/dashboard/templates/entitlements.html`
- Create: `src/eqm/dashboard/templates/hr.html`
- Create: `src/eqm/dashboard/templates/cmdb.html`
- Modify: `src/eqm/api.py`
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Append failing tests**

```python
def test_entitlements_tab(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/dashboard/entitlements")
    assert r.status_code == 200
    assert "Tier" in r.text


def test_hr_tab(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/dashboard/hr")
    assert r.status_code == 200
    assert "Role" in r.text


def test_cmdb_tab(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/dashboard/cmdb")
    assert r.status_code == 200
    assert "Criticality" in r.text
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_dashboard.py::test_entitlements_tab -v`
Expected: FAIL — 404.

- [ ] **Step 3: Create templates**

`src/eqm/dashboard/templates/entitlements.html`:
```html
{% extends "base.html" %}
{% block content %}
<h2>Entitlements ({{ items|length }})</h2>
<table>
  <thead><tr>
    <th>ID</th><th>Name</th><th>Tier</th><th>Division</th><th>Roles</th>
    <th>Linked Resources</th><th>SoD Tags</th>
  </tr></thead>
  <tbody>
  {% for e in items %}
  <tr>
    <td>{{ e.id }}</td>
    <td>{{ e.name }}</td>
    <td>{{ e.access_tier }}</td>
    <td>{{ e.division }}</td>
    <td>{{ e.acceptable_roles | join(", ") }}</td>
    <td>{{ e.linked_resource_ids | join(", ") }}</td>
    <td>{{ e.sod_tags | join(", ") }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`src/eqm/dashboard/templates/hr.html`:
```html
{% extends "base.html" %}
{% block content %}
<h2>HR Employees ({{ items|length }})</h2>
<table>
  <thead><tr>
    <th>ID</th><th>Name</th><th>Role</th><th>Division</th><th>Status</th>
    <th>Hired</th><th>Terminated</th>
  </tr></thead>
  <tbody>
  {% for e in items %}
  <tr>
    <td>{{ e.id }}</td>
    <td>{{ e.full_name }}</td>
    <td>{{ e.current_role }}</td>
    <td>{{ e.current_division }}</td>
    <td>{{ e.status }}</td>
    <td>{{ e.hired_at }}</td>
    <td>{{ e.terminated_at or "" }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`src/eqm/dashboard/templates/cmdb.html`:
```html
{% extends "base.html" %}
{% block content %}
<h2>CMDB Resources ({{ items|length }})</h2>
<table>
  <thead><tr>
    <th>ID</th><th>Name</th><th>Type</th><th>Criticality</th><th>Owner Division</th>
    <th>Environment</th><th>Linked Entitlements</th>
  </tr></thead>
  <tbody>
  {% for r in items %}
  <tr>
    <td>{{ r.id }}</td>
    <td>{{ r.name }}</td>
    <td>{{ r.type }}</td>
    <td>{{ r.criticality }}</td>
    <td>{{ r.owner_division }}</td>
    <td>{{ r.environment }}</td>
    <td>{{ r.linked_entitlement_ids | length }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 4: Append routes to `src/eqm/api.py`**

```python
@app.get("/dashboard/entitlements", response_class=HTMLResponse)
async def dashboard_entitlements(request: Request,
                                   store: JsonStore = Depends(get_store)) -> HTMLResponse:
    items = await _read_list(store, "entitlements.json")
    return templates.TemplateResponse(request, "entitlements.html",
                                       {"items": items, "scenarios": _scenarios_list()})


@app.get("/dashboard/hr", response_class=HTMLResponse)
async def dashboard_hr(request: Request,
                        store: JsonStore = Depends(get_store)) -> HTMLResponse:
    items = await _read_list(store, "hr_employees.json")
    return templates.TemplateResponse(request, "hr.html",
                                       {"items": items, "scenarios": _scenarios_list()})


@app.get("/dashboard/cmdb", response_class=HTMLResponse)
async def dashboard_cmdb(request: Request,
                          store: JsonStore = Depends(get_store)) -> HTMLResponse:
    items = await _read_list(store, "cmdb_resources.json")
    return templates.TemplateResponse(request, "cmdb.html",
                                       {"items": items, "scenarios": _scenarios_list()})
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_dashboard.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/eqm/dashboard/templates/entitlements.html src/eqm/dashboard/templates/hr.html src/eqm/dashboard/templates/cmdb.html src/eqm/api.py tests/test_dashboard.py
git commit -m "feat(dashboard): entitlements, HR, CMDB tabs with sortable tables"
```

---

## Task 35: Dashboard — violations tab with workflow history

**Files:**
- Create: `src/eqm/dashboard/templates/violations.html`
- Modify: `src/eqm/api.py`
- Modify: `src/eqm/dashboard/static/style.css`
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Append failing test**

```python
def test_violations_tab_groups_by_severity(app_client, tmp_path):
    client, token = app_client
    client.post("/simulate/reset", json={"small": True},
                headers={"Authorization": f"Bearer {token}"})
    client.post("/simulate/scenario", json={"name": "kitchen_sink"},
                headers={"Authorization": f"Bearer {token}"})
    r = client.get("/dashboard/violations")
    assert r.status_code == 200
    body = r.text
    for sev in ["critical", "high", "medium", "low"]:
        assert sev in body.lower()
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_dashboard.py::test_violations_tab_groups_by_severity -v`
Expected: FAIL — 404.

- [ ] **Step 3: Create `src/eqm/dashboard/templates/violations.html`**

```html
{% extends "base.html" %}
{% block content %}
<h2>Violations ({{ items|length }})</h2>
{% for sev in ["critical", "high", "medium", "low"] %}
  {% set bucket = items | selectattr("severity", "equalto", sev) | list %}
  {% if bucket %}
    <h3 class="sev-{{ sev }}">{{ sev|upper }} ({{ bucket|length }})</h3>
    <table>
      <thead><tr>
        <th>ID</th><th>Rule</th><th>Target</th><th>State</th>
        <th>Detected</th><th>Recommended</th><th>Explanation</th>
      </tr></thead>
      <tbody>
      {% for v in bucket %}
      <tr class="state-{{ v.workflow_state }}">
        <td>{{ v.id }}</td>
        <td>{{ v.rule_id }} — {{ v.rule_name }}</td>
        <td>{{ v.target_type }} {{ v.target_id }}</td>
        <td>{{ v.workflow_state }}</td>
        <td>{{ v.detected_at }}</td>
        <td>{{ v.recommended_action }}</td>
        <td>{{ v.explanation }}</td>
      </tr>
      {% if v.workflow_history %}
      <tr class="history-row"><td colspan="7">
        <details><summary>Workflow history ({{ v.workflow_history|length }})</summary>
        <ul>
        {% for h in v.workflow_history %}
          <li>{{ h.timestamp }} — {{ h.actor }}: {{ h.from_state }} → {{ h.to_state }}{% if h.note %} ({{ h.note }}){% endif %}</li>
        {% endfor %}
        </ul></details>
      </td></tr>
      {% endif %}
      {% endfor %}
      </tbody>
    </table>
  {% endif %}
{% endfor %}
{% endblock %}
```

Append to `style.css`:
```css
.state-resolved td { color: #888; text-decoration: line-through; }
.state-rejected td { color: #888; font-style: italic; }
.history-row td { background: #fafafa; padding-left: 2rem; }
```

- [ ] **Step 4: Append route to `src/eqm/api.py`**

```python
@app.get("/dashboard/violations", response_class=HTMLResponse)
async def dashboard_violations(request: Request,
                                 store: JsonStore = Depends(get_store)) -> HTMLResponse:
    items = await _read_list(store, "violations.json")
    return templates.TemplateResponse(request, "violations.html",
                                       {"items": items, "scenarios": _scenarios_list()})
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_dashboard.py -v`
Expected: PASS for all dashboard tests.

- [ ] **Step 6: Commit**

```bash
git add src/eqm/dashboard/ src/eqm/api.py tests/test_dashboard.py
git commit -m "feat(dashboard): violations tab grouped by severity with workflow history drawer"
```

---

## Task 36: Git integration in persistence

**Files:**
- Modify: `src/eqm/persistence.py`
- Create: `src/eqm/git_sync.py`
- Modify: `src/eqm/api.py` (replace push-now / pull-now stubs)
- Create: `tests/test_git_sync.py`

- [ ] **Step 1: Write the failing test**

`tests/test_git_sync.py`:
```python
import subprocess
from pathlib import Path

import pytest

from eqm.git_sync import GitSync


def _init_remote(remote_dir: Path) -> None:
    remote_dir.mkdir()
    subprocess.run(["git", "init", "--bare"], cwd=remote_dir, check=True,
                   capture_output=True)


def _init_local(local_dir: Path, remote_dir: Path) -> None:
    local_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=local_dir, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=local_dir, check=True)
    subprocess.run(["git", "config", "user.name", "test"],
                   cwd=local_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote_dir)],
                   cwd=local_dir, check=True)
    (local_dir / "data").mkdir()
    (local_dir / "data" / "seed.json").write_text("[]")
    subprocess.run(["git", "add", "."], cwd=local_dir, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=local_dir, check=True,
                   capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=local_dir,
                   check=True, capture_output=True)


def test_commit_and_push(tmp_path: Path):
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    _init_remote(remote)
    _init_local(local, remote)
    sync = GitSync(repo_dir=local, data_subdir="data",
                   remote_url=None, push_enabled=True)
    (local / "data" / "x.json").write_text('[{"a": 1}]')
    sync.commit_data("test commit")
    sync.push_now()
    # Verify the bare remote received it
    log = subprocess.check_output(
        ["git", "--git-dir", str(remote), "log", "--oneline"]).decode()
    assert "test commit" in log


def test_push_disabled_is_noop(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()
    sync = GitSync(repo_dir=local, data_subdir="data",
                   remote_url=None, push_enabled=False)
    # Should not raise — and not require a real repo.
    sync.commit_data("ignored")
    sync.push_now()
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/test_git_sync.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/eqm/git_sync.py`**

```python
"""Git integration for the data fabric — commit + push (and pull on demand)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from git import Repo


@dataclass(slots=True)
class GitSync:
    repo_dir: Path
    data_subdir: str
    remote_url: Optional[str]
    push_enabled: bool

    def _repo(self) -> Repo | None:
        if not self.push_enabled:
            return None
        try:
            return Repo(str(self.repo_dir))
        except Exception:
            return None

    def commit_data(self, message: str) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        repo.git.add(self.data_subdir)
        if not repo.is_dirty(untracked_files=True, path=self.data_subdir):
            return False
        repo.index.commit(message)
        return True

    def push_now(self) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        if "origin" not in [r.name for r in repo.remotes]:
            return False
        repo.remotes.origin.push()
        return True

    def pull_now(self) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        if "origin" not in [r.name for r in repo.remotes]:
            return False
        repo.remotes.origin.pull()
        return True
```

- [ ] **Step 4: Wire into API — replace stubs in `src/eqm/api.py`**

Replace the two stub endpoints `sync_push_now` and `sync_pull_now` with:

```python
from eqm.git_sync import GitSync


def get_git_sync(settings: Settings = Depends(get_settings)) -> GitSync:
    return GitSync(
        repo_dir=settings.data_dir.parent,  # repo root is one level above /data
        data_subdir=settings.data_dir.name,
        remote_url=settings.git_remote_url,
        push_enabled=settings.git_push_enabled,
    )


@app.post("/sync/push-now", dependencies=[Depends(require_token)])
async def sync_push_now(git: GitSync = Depends(get_git_sync)) -> dict:
    committed = git.commit_data("manual: push-now from API")
    pushed = git.push_now() if committed else False
    return {"committed": committed, "pushed": pushed}


@app.post("/sync/pull-now", dependencies=[Depends(require_token)])
async def sync_pull_now(git: GitSync = Depends(get_git_sync),
                         store: JsonStore = Depends(get_store)) -> dict:
    pulled = git.pull_now()
    store.invalidate()  # rebuild cache from disk on next read
    return {"pulled": pulled}
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_git_sync.py tests/test_api_simulate.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/eqm/git_sync.py src/eqm/api.py tests/test_git_sync.py
git commit -m "feat(git): GitSync wrapper with commit/push/pull, wire /sync/{push,pull}-now"
```

---

## Task 37: Dockerfile

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install -e ".[dev]"

VOLUME ["/data"]
ENV EQM_DATA_DIR=/data \
    PORT=8080

EXPOSE 8080

CMD ["uvicorn", "eqm.api:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Write `.dockerignore`**

```
.venv
.pytest_cache
.ruff_cache
__pycache__
tests
docs
data
*.md
.git
```

- [ ] **Step 3: Build and smoke-test**

Run: `docker build -t eqm:dev .`
Expected: build succeeds.

Run: `docker run --rm -e EQM_BEARER_TOKEN=t -p 8080:8080 eqm:dev` (in another terminal)
Then: `curl -s http://localhost:8080/health`
Expected: `{"status":"ok"}`

Stop the container with Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "build: Dockerfile (python 3.12-slim) with /data volume and uvicorn entrypoint"
```

---

## Task 38: fly.toml + deployment script

**Files:**
- Modify: `fly.toml`
- Create: `scripts/deploy.sh`

- [ ] **Step 1: Replace `fly.toml`**

```toml
app = "eqm-utility"
primary_region = "iad"

[build]

[env]
  EQM_DATA_DIR = "/data"
  EQM_GIT_PUSH_ENABLED = "true"

[mounts]
  source = "eqm_data"
  destination = "/data"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

  [[http_service.checks]]
    grace_period = "10s"
    interval = "30s"
    method = "GET"
    timeout = "5s"
    path = "/health"

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 512
```

- [ ] **Step 2: Create `scripts/deploy.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Sets the required Fly secrets and deploys.
# Run from the repo root after `fly auth login`.

if [ -z "${EQM_BEARER_TOKEN:-}" ]; then
  echo "EQM_BEARER_TOKEN must be set in environment before running this script." >&2
  exit 1
fi
if [ -z "${EQM_GIT_PUSH_TOKEN:-}" ]; then
  echo "EQM_GIT_PUSH_TOKEN must be set (GitHub PAT with repo:contents write)." >&2
  exit 1
fi

fly secrets set \
  EQM_BEARER_TOKEN="$EQM_BEARER_TOKEN" \
  EQM_GIT_PUSH_TOKEN="$EQM_GIT_PUSH_TOKEN" \
  EQM_GIT_REMOTE_URL="https://x-access-token:${EQM_GIT_PUSH_TOKEN}@github.com/cjmurphy4810/Entitlement-Quality-Monitor-Utility.git"

fly volumes list | grep -q eqm_data || fly volumes create eqm_data --size 1 --region iad

fly deploy
```

```bash
chmod +x scripts/deploy.sh
```

- [ ] **Step 3: Commit**

```bash
git add fly.toml scripts/deploy.sh
git commit -m "build: fly.toml with /data volume + deploy.sh that sets secrets and creates volume"
```

---

## Task 39: GitHub Actions — scheduled drift

**Files:**
- Create: `.github/workflows/simulate.yml`
- Create: `.github/workflows/test.yml`

- [ ] **Step 1: Write `.github/workflows/simulate.yml`**

```yaml
name: simulate-drift

on:
  schedule:
    - cron: "*/30 * * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Drift tick
        env:
          EQM_DATA_DIR: ${{ github.workspace }}/data
          EQM_BEARER_TOKEN: not-used-here
          EQM_GIT_PUSH_ENABLED: "0"
        run: |
          # Seed if data dir is empty
          if [ ! -s data/entitlements.json ]; then
            python -m eqm seed --small
          fi
          python -m eqm drift

      - name: Commit if changed
        run: |
          git config user.name "eqm-simulator-bot"
          git config user.email "actions@github.com"
          git add data
          if git diff --staged --quiet; then
            echo "No changes."
            exit 0
          fi
          git commit -m "chore(simulator): scheduled drift tick $(date -u +%Y-%m-%dT%H:%MZ)"
          git push
```

- [ ] **Step 2: Write `.github/workflows/test.yml`**

```yaml
name: test

on:
  push:
    branches: [main]
  pull_request:

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: ruff check src tests
      - run: pytest -q
```

- [ ] **Step 3: Smoke-test workflow syntax locally** (optional but recommended)

Run: `pip install actionlint || true; actionlint .github/workflows/*.yml`
Expected: no errors. (Skip if actionlint isn't installed.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/
git commit -m "ci: scheduled drift workflow (every 30 min) + test workflow on PR/push"
```

---

## Task 40: README + Appian connector setup guide

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# Entitlement Quality Monitor Utility

A simulated **Data Fabric** for entitlement governance, designed to be consumed by **Appian** as a Connected System. Generates and continuously mutates dummy entitlement / HR / CMDB records, runs a deterministic, fact-based **rules engine** over them, and emits violations with concrete suggested fixes — all gated by a human-in-the-loop workflow state machine.

The rules engine is **strictly deterministic**: no LLM, no fuzzy matching. Every rule is a pure Python function with unit tests. That's the Model Risk Management posture this tool exists to demonstrate.

## What's in here

- **`data/`** — JSON files that ARE the data fabric (entitlements, HR, CMDB, assignments, violations). Version-controlled audit trail.
- **`src/eqm/rules/`** — 13 deterministic rules across four categories.
- **`src/eqm/engine.py`** — runs all rules; reconciles new findings against existing violations to preserve Appian-side workflow state.
- **`src/eqm/simulator.py`** — drift mode: random, mostly-realistic mutations every 30 min via GitHub Actions.
- **`src/eqm/scenarios.py`** — seven on-cue demo scenarios (e.g. `terminated_user_with_admin`, `sod_payment_breach`).
- **`src/eqm/api.py`** — FastAPI app with read/write/simulate/sync endpoints + an HTML dashboard at `/`.
- **`fly.toml`, `Dockerfile`, `scripts/deploy.sh`** — Fly.io deployment.

## Quickstart (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

export EQM_BEARER_TOKEN=demo-token
export EQM_DATA_DIR=./data

python -m eqm seed --small
python -m eqm drift
python -m eqm scenario kitchen_sink

uvicorn eqm.api:app --reload --port 8080
# open http://localhost:8080
```

## Tests

```bash
pytest -q
ruff check src tests
```

Every rule has its own unit test file under `tests/rules/`. Adding a 14th rule = drop a file in `src/eqm/rules/`, register it, write a test.

## The 13 rules

| ID | Rule | Severity |
|---|---|---|
| ENT-Q-01 | PBL completeness | LOW |
| ENT-Q-02 | PBL template match | MEDIUM |
| ENT-Q-03 | Tier vs role coherence | HIGH |
| ENT-Q-04 | Division-resource coherence | HIGH |
| TOX-01 | Maker-checker conflict | CRITICAL |
| TOX-02 | Dev + Prod-Admin same app | CRITICAL |
| TOX-03 | Tier-1 in 3+ divisions | HIGH |
| HR-01 | Role mismatch | MEDIUM |
| HR-02 | Division mismatch | MEDIUM |
| HR-03 | Legacy entitlement (≥30d post-role-change) | HIGH |
| HR-04 | Terminated user holds active assignment | CRITICAL |
| CMDB-01 | Orphan entitlement | LOW |
| CMDB-02 | Tier inconsistency on critical resource | HIGH |

## Workflow state machine

```
OPEN → PENDING_APPROVAL → APPROVED → RESOLVED
                       → REJECTED   (terminal — suppresses re-detection)
                       → MANUAL_REPAIR → RESOLVED

REJECTED → OPEN  (only via POST /violations/{id}/reopen, compliance-driven)
```

Every transition appends an entry to `workflow_history` capturing the actor, timestamp, note, and any `override_fix`.

## Appian Connector setup

Once deployed to Fly (or any HTTPS host), wire Appian like this:

1. **Connected System** (HTTP, Bearer auth)
   - Base URL: `https://eqm-utility.fly.dev`
   - Auth: `Authorization: Bearer ${EQM_BEARER_TOKEN}`

2. **Integrations** — create one per endpoint Appian needs:
   - `GET /violations?state=open&severity=critical` — main poll
   - `POST /violations/{id}/transition` — body: `{to_state, actor, note, override_fix?}`
   - `PATCH /entitlements/{id}` — for "fix the entitlement" remediations
   - `DELETE /assignments/{id}` — for "revoke the assignment" remediations
   - `GET /hr/employees/{id}` — lookup
   - `GET /entitlements/{id}` — lookup

3. **Process model** (sketch)
   - Timer every 60s → `GET /violations?state=open` → for each:
     - First, transition to `pending_approval`: `POST /violations/{id}/transition` with `{to_state: "pending_approval", actor: "appian"}`
     - Route by severity:
       - `critical` → compliance review queue (human task)
       - `high` → entitlement-owner queue
       - `medium` / `low` → user-manager queue
     - Human task screen surfaces `evidence` + `suggested_fix` with three buttons:
       - **Approve** → call the appropriate write endpoint (PATCH/DELETE) using `suggested_fix` (or `override_fix` if the human modified it). Then transition to `approved` → `resolved`.
       - **Reject** → transition to `rejected` with a required `note`.
       - **Manual repair** → transition to `manual_repair` and surface in a separate queue for offline handling. When fixed, transition to `resolved`.

## Demo storyline (5 minutes)

See [docs/superpowers/specs/2026-04-27-entitlement-quality-monitor-utility-design.md](docs/superpowers/specs/2026-04-27-entitlement-quality-monitor-utility-design.md) §12.

## Live-demo ops note

The GitHub Actions drift workflow runs every 30 min. During a live demo, **disable the workflow** so the data fabric stays under your control:
```
gh workflow disable simulate-drift
# … run the demo …
gh workflow enable simulate-drift
```
Use `POST /sync/pull-now` if you need to pick up Actions-committed changes during a running session.

## Configuration

| Env var | Required | Default | Purpose |
|---|---|---|---|
| `EQM_BEARER_TOKEN` | yes | — | auth for write + simulate + sync endpoints |
| `EQM_DATA_DIR` | no | `./data` | where JSON files live |
| `EQM_GIT_PUSH_ENABLED` | no | `false` | enable git commit + push from API |
| `EQM_GIT_PUSH_TOKEN` | only if push enabled | — | GitHub PAT for HTTPS push |
| `EQM_GIT_REMOTE_URL` | only if push enabled | — | remote URL incl. token |

## License

Internal demo / prototype. Not for production use.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with quickstart, rules table, Appian connector setup, demo ops notes"
```

---

## Task 41: End-to-end smoke test

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Write the test**

`tests/test_e2e.py`:
```python
"""End-to-end happy path: reset → scenario → poll violations → transition → patch → resolved."""

import json


def _hdrs(token): return {"Authorization": f"Bearer {token}"}


def test_full_remediation_flow(app_client):
    client, token = app_client

    # 1. Reset to clean seed
    r = client.post("/simulate/reset", json={"small": True}, headers=_hdrs(token))
    assert r.status_code == 200

    # 2. Inject a CRITICAL scenario
    r = client.post("/simulate/scenario",
                    json={"name": "terminated_user_with_admin"},
                    headers=_hdrs(token))
    assert r.status_code == 200
    assert r.json()["new_violations"] >= 1

    # 3. Poll for the critical violation
    r = client.get("/violations?state=open&severity=critical")
    assert r.status_code == 200
    crit = r.json()
    assert len(crit) >= 1
    target = next(v for v in crit if v["rule_id"] == "HR-04")

    # 4. Transition to pending_approval (Appian picks it up)
    r = client.post(f"/violations/{target['id']}/transition",
                    json={"to_state": "pending_approval", "actor": "appian"},
                    headers=_hdrs(token))
    assert r.status_code == 200

    # 5. Apply suggested fix: revoke the assignment
    asn_id = target["target_id"]
    r = client.delete(f"/assignments/{asn_id}", headers=_hdrs(token))
    assert r.status_code == 200

    # 6. Transition to approved
    r = client.post(f"/violations/{target['id']}/transition",
                    json={"to_state": "approved", "actor": "alice@example.com",
                          "note": "Verified termination, revoked"},
                    headers=_hdrs(token))
    assert r.status_code == 200

    # 7. Transition to resolved
    r = client.post(f"/violations/{target['id']}/transition",
                    json={"to_state": "resolved", "actor": "system"},
                    headers=_hdrs(token))
    assert r.status_code == 200

    # 8. Verify workflow history captured every transition
    r = client.get(f"/violations/{target['id']}")
    final = r.json()
    states = [h["to_state"] for h in final["workflow_history"]]
    assert states == ["pending_approval", "approved", "resolved"]

    # 9. Now run an evaluate / drift tick — verify HR-04 violation does NOT
    #    re-fire for this assignment (because assignment.active is now False).
    r = client.post("/simulate/tick", headers=_hdrs(token))
    assert r.status_code == 200
    r = client.get(f"/violations?state=open")
    open_vios = r.json()
    re_detected = [v for v in open_vios if v["rule_id"] == "HR-04"
                   and v["target_id"] == asn_id]
    assert re_detected == []
```

- [ ] **Step 2: Run test to verify pass**

Run: `pytest tests/test_e2e.py -v`
Expected: PASS — full flow works end-to-end.

- [ ] **Step 3: Run the entire suite as a final gate**

Run: `pytest -q && ruff check src tests`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test(e2e): full remediation flow scenario→poll→transition→patch→resolved"
```

---

## Final commit checklist

After all 41 tasks complete:

- [ ] `pytest -q` — all tests pass
- [ ] `ruff check src tests` — no lint errors
- [ ] `docker build -t eqm:test .` — image builds
- [ ] `git log --oneline` — every task produced a focused commit
- [ ] Push to GitHub: `git push -u origin main`
- [ ] Deploy to Fly: `EQM_BEARER_TOKEN=... EQM_GIT_PUSH_TOKEN=... ./scripts/deploy.sh`
- [ ] Verify scheduled drift workflow ran successfully on GitHub Actions
- [ ] Open `https://eqm-utility.fly.dev/` — dashboard renders
- [ ] Configure Appian Connected System per README §"Appian Connector setup"
- [ ] Run the 5-minute demo storyline end-to-end as a dry run
