from dataclasses import dataclass
from enum import Enum


class CodeRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class CodeRiskCategory(str, Enum):
    SYNTAX = "syntax"
    IMPORT = "import"
    FILE_SYSTEM = "file_system"
    PROCESS = "process"
    NETWORK = "network"
    DYNAMIC_EXECUTION = "dynamic_execution"
    ENVIRONMENT = "environment"
    INTROSPECTION = "introspection"
    INFINITE_LOOP = "infinite_loop"
    RESOURCE_USAGE = "resource_usage"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class CodeSafetyFinding:
    category: CodeRiskCategory
    risk_level: CodeRiskLevel
    message: str
    line_number: int | None
    symbol: str | None


@dataclass(slots=True, frozen=True)
class CodeSafetyResult:
    parseable: bool
    overall_risk: CodeRiskLevel
    findings: tuple[CodeSafetyFinding, ...]

