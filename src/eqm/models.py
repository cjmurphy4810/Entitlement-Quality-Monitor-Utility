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
