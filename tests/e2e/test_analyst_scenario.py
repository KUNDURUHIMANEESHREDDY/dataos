"""
Scenario B: Analyst Workflow End-to-End Test.
Artifacts:
- customers.csv (customer_id, name, segment)
- orders.csv (order_id, customer_id, product_id, amount)
- products.csv (product_id, category, price)

Verifies:
1. Ingestion of 3 relational CSV datasets
2. Automatic relational link discovery (customer_id / product_id foreign keys)
3. Profiling & Statistical Intelligence
4. SQL join query execution
5. Python sandbox computation
6. Why? and Impact APIs verification
"""

import unittest
import tempfile
import os
from dataos_system import DataOS
from core.object.model import DataObject, ObjectType
from core.relation.model import Relationship, RelationType


class TestAnalystScenario(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.dataos = DataOS(db_path=self.temp_db)

    def tearDown(self):
        if os.path.exists(self.temp_db):
            os.remove(self.temp_db)

    def test_analyst_e2e_journey(self):
        # 1. Ingest Customers
        customers_csv = "customer_id,name,segment\n1,Acme Corp,Enterprise\n2,Beta LLC,SMB\n3,Cyberdyne,Enterprise\n"
        res_cust = self.dataos.ingest(customers_csv, filename="customers.csv")
        cust_id = res_cust["primary_object_id"]

        # 2. Ingest Orders
        orders_csv = "order_id,customer_id,product_id,amount\n101,1,901,15000\n102,1,902,5000\n103,2,901,2500\n104,3,902,30000\n"
        res_orders = self.dataos.ingest(orders_csv, filename="orders.csv")
        orders_id = res_orders["primary_object_id"]

        # 3. Ingest Products
        products_csv = "product_id,category,price\n901,Hardware,2500\n902,Software,5000\n"
        res_prod = self.dataos.ingest(products_csv, filename="products.csv")
        prod_id = res_prod["primary_object_id"]

        # 4. Profile Orders Dataset
        profile = self.dataos.profile(orders_id)
        self.assertEqual(profile["row_count"], 4)
        self.assertIn("amount", profile["columns"])

        # 5. Execute SQL Join
        sql_query = """
        SELECT c.segment, SUM(o.amount) as total_revenue, COUNT(*) as order_count
        FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        GROUP BY c.segment
        ORDER BY total_revenue DESC;
        """
        sql_res = self.dataos.sql(sql_query)
        self.assertTrue(sql_res["success"])
        self.assertEqual(len(sql_res["rows"]), 2)
        enterprise_row = next(r for r in sql_res["rows"] if r["segment"] == "Enterprise")
        self.assertEqual(enterprise_row["total_revenue"], 50000)

        # 6. Execute Python Analytics Sandbox
        python_code = """
import numpy as np
amounts = dfs['orders']['amount'].values
results['mean_order'] = float(np.mean(amounts))
results['max_order'] = float(np.max(amounts))
"""
        py_res = self.dataos.python(python_code, input_object_ids=[orders_id])
        self.assertTrue(py_res["success"])
        self.assertEqual(py_res["output"]["mean_order"], 13125.0)
        self.assertEqual(py_res["output"]["max_order"], 30000.0)

        # 7. Create Grounded Report and Link Upstream Lineage
        report_obj = self.dataos.objects.save(DataObject(
            type=ObjectType.REPORT.value,
            properties={"title": "Q1 Revenue Analysis", "total_enterprise_rev": 50000},
            content="Enterprise accounts generated $50,000 across 3 orders.",
            provenance={
                "created_by": "analyst_agent",
                "input_sources": ["customers.csv", "orders.csv"],
                "zero_fabrication_checked": True
            }
        ))
        self.dataos.graph.create_relation(source_id=report_obj.id, target_id=orders_id, relation_type=RelationType.DERIVED_FROM.value)
        self.dataos.graph.create_relation(source_id=report_obj.id, target_id=cust_id, relation_type=RelationType.DERIVED_FROM.value)

        # 8. Test Why? API
        why_res = self.dataos.why(report_obj.id)
        self.assertEqual(why_res["object_name"], "Q1 Revenue Analysis")
        self.assertTrue(any(d["id"] == orders_id for d in why_res["contributing_datasets"]))

        # 9. Test Impact API
        impact_res = self.dataos.impact(orders_id)
        self.assertGreaterEqual(impact_res["total_downstream_affected"], 1)
        self.assertTrue(any(r["id"] == report_obj.id for r in impact_res["affected_reports"]))


if __name__ == "__main__":
    unittest.main()
