"""
Tests for Data Contracts (Rule #60).
Validates rule creation, contract management, validation, and enforcement.
"""

import unittest
import datetime
from engines.governance.data_contracts import (
    DataContractsManager, DataContract, ContractRule, RuleType,
    ContractStatus, ContractValidator, ValidationResult,
)


class TestContractValidator(unittest.TestCase):

    def setUp(self):
        self.validator = ContractValidator()

    def test_validate_schema(self):
        rule = ContractRule("r1", RuleType.SCHEMA, "table", parameters={"fields": {"name": "string", "age": "int"}})
        data = [{"name": "Alice", "age": 30}]
        result = self.validator.validate_rule(rule, data)
        self.assertTrue(result.passed)

    def test_validate_schema_missing_field(self):
        rule = ContractRule("r1", RuleType.SCHEMA, "table", parameters={"fields": {"name": "string", "email": "string"}})
        data = [{"name": "Alice"}]
        result = self.validator.validate_rule(rule, data)
        self.assertFalse(result.passed)
        self.assertIn("email", result.message)

    def test_validate_not_null(self):
        rule = ContractRule("r1", RuleType.NOT_NULL, "name")
        data = [{"name": "Alice"}, {"name": "Bob"}]
        result = self.validator.validate_rule(rule, data)
        self.assertTrue(result.passed)

    def test_validate_not_null_fails(self):
        rule = ContractRule("r1", RuleType.NOT_NULL, "name")
        data = [{"name": "Alice"}, {"name": None}]
        result = self.validator.validate_rule(rule, data)
        self.assertFalse(result.passed)
        self.assertEqual(result.details["null_count"], 1)

    def test_validate_unique(self):
        rule = ContractRule("r1", RuleType.UNIQUE, "id")
        data = [{"id": 1}, {"id": 2}, {"id": 3}]
        result = self.validator.validate_rule(rule, data)
        self.assertTrue(result.passed)

    def test_validate_unique_fails(self):
        rule = ContractRule("r1", RuleType.UNIQUE, "id")
        data = [{"id": 1}, {"id": 1}]
        result = self.validator.validate_rule(rule, data)
        self.assertFalse(result.passed)

    def test_validate_range(self):
        rule = ContractRule("r1", RuleType.RANGE, "score", parameters={"min": 0, "max": 100})
        data = [{"score": 50}, {"score": 75}]
        result = self.validator.validate_rule(rule, data)
        self.assertTrue(result.passed)

    def test_validate_range_fails(self):
        rule = ContractRule("r1", RuleType.RANGE, "score", parameters={"min": 0, "max": 100})
        data = [{"score": 150}]
        result = self.validator.validate_rule(rule, data)
        self.assertFalse(result.passed)

    def test_validate_regex(self):
        rule = ContractRule("r1", RuleType.REGEX, "email", parameters={"pattern": r"^[a-z]+@[a-z]+\.[a-z]+$"})
        data = [{"email": "alice@test.com"}]
        result = self.validator.validate_rule(rule, data)
        self.assertTrue(result.passed)

    def test_validate_regex_fails(self):
        rule = ContractRule("r1", RuleType.REGEX, "email", parameters={"pattern": r"^[a-z]+@[a-z]+\.[a-z]+$"})
        data = [{"email": "INVALID"}]
        result = self.validator.validate_rule(rule, data)
        self.assertFalse(result.passed)

    def test_validate_freshness(self):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rule = ContractRule("r1", RuleType.FRESHNESS, "data", parameters={"max_age_hours": 24, "timestamp_field": "updated_at"})
        data = [{"updated_at": now}]
        result = self.validator.validate_rule(rule, data)
        self.assertTrue(result.passed)

    def test_validate_freshness_stale(self):
        stale = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)).isoformat()
        rule = ContractRule("r1", RuleType.FRESHNESS, "data", parameters={"max_age_hours": 24, "timestamp_field": "updated_at"})
        data = [{"updated_at": stale}]
        result = self.validator.validate_rule(rule, data)
        self.assertFalse(result.passed)

    def test_validate_completeness(self):
        rule = ContractRule("r1", RuleType.COMPLETENESS, "email", parameters={"min_percent": 60})
        data = [{"email": "a@b.com"}, {"email": ""}, {"email": "c@d.com"}]
        result = self.validator.validate_rule(rule, data)
        self.assertTrue(result.passed)

    def test_validate_completeness_fails(self):
        rule = ContractRule("r1", RuleType.COMPLETENESS, "email", parameters={"min_percent": 100})
        data = [{"email": "a@b.com"}, {"email": ""}]
        result = self.validator.validate_rule(rule, data)
        self.assertFalse(result.passed)

    def test_validate_custom(self):
        def even_check(data, params):
            vals = [r.get("val", 0) for r in data] if isinstance(data, list) else []
            bad = sum(1 for v in vals if v % 2 != 0)
            return ValidationResult("custom", bad == 0, f"{bad} odd values")
        self.validator.register_validator("even_check", even_check)
        rule = ContractRule("r1", RuleType.CUSTOM, "even_check")
        result = self.validator.validate_rule(rule, [{"val": 2}, {"val": 4}])
        self.assertTrue(result.passed)


class TestDataContract(unittest.TestCase):

    def test_contract_creation(self):
        contract = DataContract(
            contract_id="c1",
            name="Test Contract",
            owner="admin",
            dataset_id="ds1",
            rules=[ContractRule("r1", RuleType.NOT_NULL, "name")],
        )
        self.assertEqual(contract.contract_id, "c1")
        self.assertEqual(len(contract.rules), 1)

    def test_add_rule(self):
        contract = DataContract(contract_id="c1", name="C", owner="admin", dataset_id="ds1")
        contract.add_rule(ContractRule("r1", RuleType.UNIQUE, "id"))
        self.assertEqual(len(contract.rules), 1)

    def test_to_dict(self):
        contract = DataContract(contract_id="c1", name="C", owner="admin", dataset_id="ds1")
        d = contract.to_dict()
        self.assertEqual(d["contract_id"], "c1")
        self.assertEqual(d["status"], "active")


class TestDataContractsManager(unittest.TestCase):

    def setUp(self):
        self.manager = DataContractsManager()

    def test_create_contract(self):
        contract = self.manager.create_contract("Test", "admin", "ds1")
        self.assertIsNotNone(contract.contract_id)
        self.assertEqual(contract.name, "Test")

    def test_get_contract(self):
        contract = self.manager.create_contract("Test", "admin", "ds1")
        found = self.manager.get_contract(contract.contract_id)
        self.assertIsNotNone(found)

    def test_list_contracts(self):
        self.manager.create_contract("C1", "admin", "ds1")
        self.manager.create_contract("C2", "admin", "ds2")
        all_contracts = self.manager.list_contracts()
        self.assertEqual(len(all_contracts), 2)

    def test_list_contracts_filter(self):
        self.manager.create_contract("C1", "admin", "ds1")
        self.manager.create_contract("C2", "admin", "ds2")
        filtered = self.manager.list_contracts(dataset_id="ds1")
        self.assertEqual(len(filtered), 1)

    def test_delete_contract(self):
        contract = self.manager.create_contract("Test", "admin", "ds1")
        self.assertTrue(self.manager.delete_contract(contract.contract_id))
        self.assertIsNone(self.manager.get_contract(contract.contract_id))

    def test_validate_dataset(self):
        rules = [
            ContractRule("r1", RuleType.NOT_NULL, "name"),
            ContractRule("r2", RuleType.UNIQUE, "id"),
        ]
        contract = self.manager.create_contract("Test", "admin", "ds1", rules=rules)
        data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        report = self.manager.validate_dataset(contract.contract_id, data)
        self.assertEqual(report["status"], "valid")
        self.assertEqual(report["passed"], 2)

    def test_validate_violation(self):
        rules = [ContractRule("r1", RuleType.NOT_NULL, "name")]
        contract = self.manager.create_contract("Test", "admin", "ds1", rules=rules)
        data = [{"name": None}]
        report = self.manager.validate_dataset(contract.contract_id, data)
        self.assertEqual(report["status"], "violated")
        self.assertEqual(report["failed"], 1)
        self.assertEqual(contract.status, ContractStatus.VIOLATED)

    def test_validate_nonexistent_contract(self):
        report = self.manager.validate_dataset("no_such", [])
        self.assertIn("error", report)

    def test_validation_history(self):
        contract = self.manager.create_contract("Test", "admin", "ds1", rules=[ContractRule("r1", RuleType.NOT_NULL, "x")])
        self.manager.validate_dataset(contract.contract_id, [{"x": 1}])
        self.manager.validate_dataset(contract.contract_id, [{"x": 2}])
        history = self.manager.get_validation_history(contract.contract_id)
        self.assertEqual(len(history), 2)

    def test_stats(self):
        self.manager.create_contract("C1", "admin", "ds1")
        self.manager.create_contract("C2", "admin", "ds1")
        stats = self.manager.get_stats()
        self.assertEqual(stats["total_contracts"], 2)


class TestRuleType(unittest.TestCase):

    def test_all_types(self):
        for rt in RuleType:
            self.assertIsInstance(rt.value, str)


if __name__ == "__main__":
    unittest.main()
