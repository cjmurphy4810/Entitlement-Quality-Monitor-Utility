"""Pydantic models and enums for the Entitlement Quality Monitor."""

from enum import IntEnum, StrEnum


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
