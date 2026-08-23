"""
Tests for Data Catalog (Rule #37).
Validates entry management, search, lineage, profiling, and freshness.
"""

import unittest
import datetime
from engines.catalog.data_catalog import DataCatalog, CatalogEntry, CatalogEntryType


class TestDataCatalog(unittest.TestCase):

    def setUp(self):
        self.catalog = DataCatalog()

    def test_add_entry(self):
        entry = self.catalog.add_entry(CatalogEntryType.DATASET, "users", owner="admin")
        self.assertIsNotNone(entry.entry_id)
        self.assertEqual(entry.name, "users")

    def test_get_entry(self):
        entry = self.catalog.add_entry(CatalogEntryType.TABLE, "orders")
        found = self.catalog.get_entry(entry.entry_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "orders")

    def test_update_entry(self):
        entry = self.catalog.add_entry(CatalogEntryType.COLUMN, "email")
        self.assertTrue(self.catalog.update_entry(entry.entry_id, description="Email address"))
        found = self.catalog.get_entry(entry.entry_id)
        self.assertEqual(found.description, "Email address")

    def test_update_tags(self):
        entry = self.catalog.add_entry(CatalogEntryType.DATASET, "ds1", tags=["raw"])
        self.assertTrue(self.catalog.update_entry(entry.entry_id, tags=["processed", "clean"]))
        results = self.catalog.search(tags=["clean"])
        self.assertEqual(len(results), 1)

    def test_delete_entry(self):
        entry = self.catalog.add_entry(CatalogEntryType.PIPELINE, "etl1")
        self.assertTrue(self.catalog.delete_entry(entry.entry_id))
        self.assertIsNone(self.catalog.get_entry(entry.entry_id))

    def test_delete_nonexistent(self):
        self.assertFalse(self.catalog.delete_entry("no_such"))

    def test_search_by_name(self):
        self.catalog.add_entry(CatalogEntryType.DATASET, "user_events")
        self.catalog.add_entry(CatalogEntryType.DATASET, "order_events")
        results = self.catalog.search(query="user")
        self.assertEqual(len(results), 1)

    def test_search_by_type(self):
        self.catalog.add_entry(CatalogEntryType.DATASET, "ds1")
        self.catalog.add_entry(CatalogEntryType.TABLE, "t1")
        results = self.catalog.search(entry_type=CatalogEntryType.TABLE)
        self.assertEqual(len(results), 1)

    def test_search_by_tag(self):
        self.catalog.add_entry(CatalogEntryType.DATASET, "ds1", tags=["pii", "sensitive"])
        self.catalog.add_entry(CatalogEntryType.DATASET, "ds2", tags=["public"])
        results = self.catalog.search(tags=["pii"])
        self.assertEqual(len(results), 1)

    def test_search_by_owner(self):
        self.catalog.add_entry(CatalogEntryType.DATASET, "ds1", owner="alice")
        self.catalog.add_entry(CatalogEntryType.DATASET, "ds2", owner="bob")
        results = self.catalog.search(owner="alice")
        self.assertEqual(len(results), 1)

    def test_lineage(self):
        e1 = self.catalog.add_entry(CatalogEntryType.DATASET, "raw")
        e2 = self.catalog.add_entry(CatalogEntryType.DATASET, "processed")
        self.catalog.add_lineage(e2.entry_id, e1.entry_id)
        upstream = self.catalog.get_upstream(e2.entry_id)
        self.assertEqual(len(upstream), 1)
        downstream = self.catalog.get_downstream(e1.entry_id)
        self.assertEqual(len(downstream), 1)

    def test_lineage_no_duplicates(self):
        e1 = self.catalog.add_entry(CatalogEntryType.DATASET, "a")
        e2 = self.catalog.add_entry(CatalogEntryType.DATASET, "b")
        self.catalog.add_lineage(e2.entry_id, e1.entry_id)
        self.catalog.add_lineage(e2.entry_id, e1.entry_id)
        upstream = self.catalog.get_upstream(e2.entry_id)
        self.assertEqual(len(upstream), 1)

    def test_auto_profile(self):
        entry = self.catalog.add_entry(CatalogEntryType.TABLE, "t1")
        self.assertTrue(self.catalog.auto_profile(entry.entry_id, {"row_count": 1000, "null_rate": 0.05}))
        found = self.catalog.get_entry(entry.entry_id)
        self.assertEqual(found.metadata["profile"]["row_count"], 1000)

    def test_auto_profile_nonexistent(self):
        self.assertFalse(self.catalog.auto_profile("no_such", {}))

    def test_freshness_fresh(self):
        entry = self.catalog.add_entry(CatalogEntryType.DATASET, "ds1")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.catalog.update_freshness(entry.entry_id, now)
        found = self.catalog.get_entry(entry.entry_id)
        self.assertEqual(found.freshness_status, "fresh")

    def test_freshness_stale(self):
        entry = self.catalog.add_entry(CatalogEntryType.DATASET, "ds1")
        stale = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)).isoformat()
        self.catalog.update_freshness(entry.entry_id, stale)
        found = self.catalog.get_entry(entry.entry_id)
        self.assertEqual(found.freshness_status, "stale")

    def test_freshness_expired(self):
        entry = self.catalog.add_entry(CatalogEntryType.DATASET, "ds1")
        expired = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat()
        self.catalog.update_freshness(entry.entry_id, expired)
        found = self.catalog.get_entry(entry.entry_id)
        self.assertEqual(found.freshness_status, "expired")

    def test_stats(self):
        self.catalog.add_entry(CatalogEntryType.DATASET, "ds1")
        self.catalog.add_entry(CatalogEntryType.TABLE, "t1")
        stats = self.catalog.get_stats()
        self.assertEqual(stats["total_entries"], 2)
        self.assertEqual(stats["by_type"]["dataset"], 1)
        self.assertEqual(stats["by_type"]["table"], 1)

    def test_export_metadata(self):
        self.catalog.add_entry(CatalogEntryType.DATASET, "ds1")
        self.catalog.add_entry(CatalogEntryType.DATASET, "ds2")
        export = self.catalog.export_metadata()
        self.assertEqual(len(export), 2)

    def test_search_limit(self):
        for i in range(10):
            self.catalog.add_entry(CatalogEntryType.DATASET, f"ds{i}")
        results = self.catalog.search(limit=3)
        self.assertEqual(len(results), 3)


class TestCatalogEntry(unittest.TestCase):

    def test_to_dict(self):
        entry = CatalogEntry("e1", CatalogEntryType.DATASET, "test", owner="admin", tags=["tag1"])
        d = entry.to_dict()
        self.assertEqual(d["entry_id"], "e1")
        self.assertEqual(d["entry_type"], "dataset")
        self.assertIn("tag1", d["tags"])


class TestCatalogEntryType(unittest.TestCase):

    def test_all_types(self):
        self.assertEqual(len(CatalogEntryType), 5)


if __name__ == "__main__":
    unittest.main()
