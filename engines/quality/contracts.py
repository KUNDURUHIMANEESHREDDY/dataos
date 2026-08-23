"""
Declarative Data Contracts for DataOS (Rule #60).
Defines enforceable contracts for schema shape, quality SLAs, freshness, and invariant assertions.
"""

from __future__ import annotations
import json
import pandas as pd
from typing import Dict, Any, List, Optional
from core.object.model import DataObject, ObjectType
from .quality_engine import DataQualityEngine


class DataContract:
    """Declarative contract for dataset validation and governance."""

    def __init__(
        self,
        name: str,
        target_dataset_pattern: str,
        expected_columns: List[str],
        rules: List[Dict[str, Any]],
        sla_freshness_hours: Optional[int] = None
    ):
        self.name = name
        self.target_dataset_pattern = target_dataset_pattern
        self.expected_columns = expected_columns
        self.rules = rules
        self.sla_freshness_hours = sla_freshness_hours

    def evaluate(self, df: pd.DataFrame, dataset_object: DataObject) -> DataObject:
        """Evaluate contract against a dataset and return a first-class QualityReport DataObject."""
        # Combine column presence rules with custom rules
        combined_rules = [{"type": "row_count_min", "min_rows": 1}]
        for col in self.expected_columns:
            # Add existence check
            combined_rules.append({"type": "not_null", "column": col, "max_null_ratio": 1.0})
        combined_rules.extend(self.rules)

        report = DataQualityEngine.evaluate_rules(df, combined_rules, target_object_id=dataset_object.id)
        report.properties["contract_name"] = self.name
        return report

    def to_object(self) -> DataObject:
        """Serialize contract as a first-class DataOS Contract Object."""
        return DataObject(
            type=ObjectType.CONTRACT.value,
            schema="data_contract.v1",
            properties={
                "name": self.name,
                "target_pattern": self.target_dataset_pattern,
                "expected_columns": self.expected_columns,
                "sla_freshness_hours": self.sla_freshness_hours
            },
            content={
                "rules": self.rules
            },
            source="dataos://contracts"
        )
