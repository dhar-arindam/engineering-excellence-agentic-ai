"""Domain enumerations."""
from enum import Enum


class AgentName(str, Enum):
    SENIOR_QA = "SeniorQAAgent"
    SENIOR_DEVELOPER = "SeniorDeveloperAgent"
    SENIOR_ARCHITECT = "SeniorArchitectAgent"
    SENIOR_SRE = "SeniorSREAgent"
    SECURITY_EXPERT = "SecurityExpertAgent"


class Severity(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class RiskLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ScanStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
