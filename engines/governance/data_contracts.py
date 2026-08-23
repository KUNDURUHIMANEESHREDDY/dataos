"""
Data Contracts Engine for DataOS (Rule #60).
Defines enforceable expectations for data quality and structure.
Supports schema validation, freshness, completeness, and custom rules.
"""

from __future__ import annotations
import uuid
import datetime
import re
from typing import Dict, Any, List, Optional, Callable
from enum import Enum


class ContractStatus(str, Enum):
    """Lifecycle status of a data contract."""
    ACTIVE = "active"
    VIOLATED = "violated"
    EXEMPT = "exempt"
    RETIRED = "retired"


class RuleType(str, Enum):
    """Types of validation rules in a data contract."""
    SCHEMA = "schema"
    NOT_NULL = "not_null"
    UNIQUE = "unique"
    RANGE = "range"
    REGEX = "regex"
    FRESHNESS = "freshness"
    COMPLETENESS = "completeness"
    REFERENTIAL = "referential"
    CUSTOM = "custom"


class ContractRule:
    """A single enforceable rule within a data contract."""

    def __init__(
        self,
        rule_id: str,
        rule_type: RuleType,
        target: str,
        parameters: Optional[Dict[str, Any]] = None,
        severity: str = "error",
        description: str = "",
    ):
        self.rule_id = rule_id
        self.rule_type = rule_type
        self.target = target
        self.parameters = parameters or {}
        self.severity = severity
        self.description = description

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the contract rule to a dictionary."""
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type.value,
            "target": self.target,
            "parameters": self.parameters,
            "severity": self.severity,
            "description": self.description,
        }


class ValidationResult:
    """Result of validating a single rule."""

    def __init__(self, rule_id: str, passed: bool, message: str = "", details: Optional[Dict[str, Any]] = None):
        self.rule_id = rule_id
        self.passed = passed
        self.message = message
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the validation result to a dictionary."""
        return {"rule_id": self.rule_id, "passed": self.passed, "message": self.message, "details": self.details}


class DataContract:
    """A data contract defining expectations for a dataset."""

    def __init__(
        self,
        contract_id: str,
        name: str,
        owner: str,
        dataset_id: str,
        rules: Optional[List[ContractRule]] = None,
        description: str = "",
        version: str = "1.0.0",
        status: ContractStatus = ContractStatus.ACTIVE,
    ):
        self.contract_id = contract_id or str(uuid.uuid4())[:12]
        self.name = name
        self.owner = owner
        self.dataset_id = dataset_id
        self.rules = rules or []
        self.description = description
        self.version = version
        self.status = status
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def add_rule(self, rule: ContractRule) -> None:
        """Append a rule to the contract."""
        self.rules.append(rule)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the data contract to a dictionary."""
        return {
            "contract_id": self.contract_id,
            "name": self.name,
            "owner": self.owner,
            "dataset_id": self.dataset_id,
            "description": self.description,
            "version": self.version,
            "status": self.status.value,
            "rules": [r.to_dict() for r in self.rules],
            "created_at": self.created_at,
        }


class ContractValidator:
    """Validates data against contract rules."""

    def __init__(self):
        self._custom_validators: Dict[str, Callable] = {}

    def register_validator(self, rule_type: str, validator: Callable[[Any, Dict[str, Any]], ValidationResult]) -> None:
        """Register a custom validator for a rule type."""
        self._custom_validators[rule_type] = validator

    def validate_rule(self, rule: ContractRule, data: Any) -> ValidationResult:
        """Validate a single rule against data."""
        if rule.rule_type == RuleType.SCHEMA:
            return self._validate_schema(rule, data)
        elif rule.rule_type == RuleType.NOT_NULL:
            return self._validate_not_null(rule, data)
        elif rule.rule_type == RuleType.UNIQUE:
            return self._validate_unique(rule, data)
        elif rule.rule_type == RuleType.RANGE:
            return self._validate_range(rule, data)
        elif rule.rule_type == RuleType.REGEX:
            return self._validate_regex(rule, data)
        elif rule.rule_type == RuleType.FRESHNESS:
            return self._validate_freshness(rule, data)
        elif rule.rule_type == RuleType.COMPLETENESS:
            return self._validate_completeness(rule, data)
        elif rule.rule_type == RuleType.CUSTOM:
            handler = self._custom_validators.get(rule.target)
            if handler:
                return handler(data, rule.parameters)
            return ValidationResult(rule.rule_id, False, f"No custom validator for '{rule.target}'")
        return ValidationResult(rule.rule_id, True, "Rule type not applicable")

    def validate_all(self, rules: List[ContractRule], data: Any) -> List[ValidationResult]:
        """Validate all rules against data and return results."""
        return [self.validate_rule(r, data) for r in rules]

    def _validate_schema(self, rule: ContractRule, data: Any) -> ValidationResult:
        """Validate that data matches expected schema (column names, types)."""
        if not isinstance(data, (list, dict)):
            return ValidationResult(rule.rule_id, False, "Data is not tabular")

        expected_fields = rule.parameters.get("fields", {})
        if isinstance(data, list) and len(data) > 0:
            actual_fields = set(data[0].keys()) if isinstance(data[0], dict) else set()
        elif isinstance(data, dict):
            actual_fields = set(data.keys())
        else:
            actual_fields = set()

        missing = set(expected_fields.keys()) - actual_fields
        if missing:
            return ValidationResult(rule.rule_id, False, f"Missing fields: {missing}", {"missing": list(missing)})
        return ValidationResult(rule.rule_id, True, "Schema valid")

    def _validate_not_null(self, rule: ContractRule, data: Any) -> ValidationResult:
        """Validate that a column has no null values."""
        column = rule.target
        if not isinstance(data, list):
            return ValidationResult(rule.rule_id, True, "Not applicable to non-list data")

        nulls = sum(1 for row in data if row.get(column) is None or row.get(column) == "")
        if nulls > 0:
            return ValidationResult(rule.rule_id, False, f"{nulls} null values in '{column}'", {"null_count": nulls})
        return ValidationResult(rule.rule_id, True, f"No nulls in '{column}'")

    def _validate_unique(self, rule: ContractRule, data: Any) -> ValidationResult:
        """Validate that a column has unique values."""
        column = rule.target
        if not isinstance(data, list):
            return ValidationResult(rule.rule_id, True, "Not applicable")

        values = [row.get(column) for row in data]
        seen = set()
        dupes = 0
        for v in values:
            if v in seen:
                dupes += 1
            seen.add(v)
        if dupes > 0:
            return ValidationResult(rule.rule_id, False, f"{dupes} duplicates in '{column}'", {"duplicate_count": dupes})
        return ValidationResult(rule.rule_id, True, f"All values unique in '{column}'")

    def _validate_range(self, rule: ContractRule, data: Any) -> ValidationResult:
        """Validate that column values fall within a range."""
        column = rule.target
        min_val = rule.parameters.get("min")
        max_val = rule.parameters.get("max")
        if not isinstance(data, list):
            return ValidationResult(rule.rule_id, True, "Not applicable")

        violations = 0
        for row in data:
            val = row.get(column)
            if val is not None:
                if min_val is not None and val < min_val:
                    violations += 1
                if max_val is not None and val > max_val:
                    violations += 1
        if violations > 0:
            return ValidationResult(rule.rule_id, False, f"{violations} values out of range in '{column}'", {"violations": violations})
        return ValidationResult(rule.rule_id, True, f"All values in range for '{column}'")

    def _validate_regex(self, rule: ContractRule, data: Any) -> ValidationResult:
        """Validate that column values match a regex pattern."""
        column = rule.target
        pattern = rule.parameters.get("pattern", "")
        if not isinstance(data, list):
            return ValidationResult(rule.rule_id, True, "Not applicable")

        regex = re.compile(pattern)
        violations = sum(1 for row in data if not regex.match(str(row.get(column, ""))))
        if violations > 0:
            return ValidationResult(rule.rule_id, False, f"{violations} values don't match pattern in '{column}'", {"violations": violations})
        return ValidationResult(rule.rule_id, True, f"All values match pattern in '{column}'")

    def _validate_freshness(self, rule: ContractRule, data: Any) -> ValidationResult:
        """Validate that data is fresh (within max_age_hours)."""
        max_age_hours = rule.parameters.get("max_age_hours", 24)
        timestamp_field = rule.parameters.get("timestamp_field", "updated_at")

        if isinstance(data, dict):
            ts = data.get(timestamp_field)
        elif isinstance(data, list) and len(data) > 0:
            ts = data[0].get(timestamp_field) if isinstance(data[0], dict) else None
        else:
            ts = None

        if ts is None:
            return ValidationResult(rule.rule_id, False, f"No timestamp found in '{timestamp_field}'")

        try:
            dt = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            age_hours = (datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds() / 3600
            if age_hours > max_age_hours:
                return ValidationResult(rule.rule_id, False, f"Data is {age_hours:.1f}h old (max {max_age_hours}h)", {"age_hours": round(age_hours, 1)})
        except (ValueError, TypeError):
            return ValidationResult(rule.rule_id, False, f"Cannot parse timestamp '{ts}'")

        return ValidationResult(rule.rule_id, True, "Data is fresh")

    def _validate_completeness(self, rule: ContractRule, data: Any) -> ValidationResult:
        """Validate that a minimum percentage of values are non-null."""
        column = rule.target
        min_percent = rule.parameters.get("min_percent", 100)
        if not isinstance(data, list) or len(data) == 0:
            return ValidationResult(rule.rule_id, True, "Not applicable")

        total = len(data)
        non_null = sum(1 for row in data if row.get(column) is not None and row.get(column) != "")
        actual_percent = (non_null / total) * 100
        if actual_percent < min_percent:
            return ValidationResult(rule.rule_id, False, f"Completeness {actual_percent:.1f}% < {min_percent}% for '{column}'", {"actual_percent": round(actual_percent, 1)})
        return ValidationResult(rule.rule_id, True, f"Completeness {actual_percent:.1f}% >= {min_percent}%")


class DataContractsManager:
    """Central manager for all data contracts."""

    def __init__(self):
        self._contracts: Dict[str, DataContract] = {}
        self._validator = ContractValidator()
        self._validation_history: List[Dict[str, Any]] = []

    def create_contract(
        self,
        name: str,
        owner: str,
        dataset_id: str,
        rules: Optional[List[ContractRule]] = None,
        description: str = "",
    ) -> DataContract:
        """Create and register a new data contract."""
        contract = DataContract(
            contract_id=str(uuid.uuid4())[:12],
            name=name,
            owner=owner,
            dataset_id=dataset_id,
            rules=rules or [],
            description=description,
        )
        self._contracts[contract.contract_id] = contract
        return contract

    def get_contract(self, contract_id: str) -> Optional[DataContract]:
        """Retrieve a contract by its ID."""
        return self._contracts.get(contract_id)

    def list_contracts(self, dataset_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all contracts, optionally filtered by dataset."""
        contracts = list(self._contracts.values())
        if dataset_id:
            contracts = [c for c in contracts if c.dataset_id == dataset_id]
        return [c.to_dict() for c in contracts]

    def delete_contract(self, contract_id: str) -> bool:
        """Remove a contract by its ID."""
        if contract_id in self._contracts:
            del self._contracts[contract_id]
            return True
        return False

    def validate_dataset(self, contract_id: str, data: Any) -> Dict[str, Any]:
        """Validate data against a contract. Returns full validation report."""
        contract = self._contracts.get(contract_id)
        if not contract:
            return {"error": f"Contract '{contract_id}' not found"}

        results = self._validator.validate_all(contract.rules, data)
        passed = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if not r.passed)

        report = {
            "contract_id": contract_id,
            "contract_name": contract.name,
            "dataset_id": contract.dataset_id,
            "total_rules": len(results),
            "passed": passed,
            "failed": failed,
            "status": "valid" if failed == 0 else "violated",
            "results": [r.to_dict() for r in results],
            "validated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        if failed > 0:
            contract.status = ContractStatus.VIOLATED

        self._validation_history.append(report)
        return report

    def get_validation_history(self, contract_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Return validation history, optionally filtered by contract."""
        history = self._validation_history
        if contract_id:
            history = [h for h in history if h.get("contract_id") == contract_id]
        return history[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics for all contracts."""
        by_status = {}
        for c in self._contracts.values():
            s = c.status.value
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "total_contracts": len(self._contracts),
            "by_status": by_status,
            "total_validations": len(self._validation_history),
        }
