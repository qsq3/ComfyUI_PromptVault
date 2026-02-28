import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from promptvault.db import PromptVaultStore


class PromptVaultImportExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "promptvault.db")
        patcher = mock.patch("promptvault.db.get_db_path", return_value=self.db_path)
        self.addCleanup(patcher.stop)
        patcher.start()
        self.store = PromptVaultStore()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _seed_data(self):
        self.store.upsert_template(
            {
                "id": "tpl_demo",
                "title": "模板A",
                "ir": {"segments": [{"type": "literal", "text": "hello"}]},
            }
        )
        self.store.upsert_fragment(
            {
                "id": "frag_demo",
                "title": "片段A",
                "text": "cinematic lighting",
                "tags": ["light"],
                "model_scope": ["SDXL"],
            }
        )
        self.store.create_entry(
            {
                "id": "entry_demo",
                "title": "记录A",
                "template_id": "tpl_demo",
                "tags": ["portrait"],
                "model_scope": ["SDXL"],
                "variables": {"subject": "cat"},
                "fragments": [{"id": "frag_demo", "weight": 1.1}],
                "raw": {"positive": "best quality", "negative": "lowres"},
                "params": {"steps": 30, "cfg": 7},
            }
        )

    def test_export_bundle_json_contains_all_record_types(self):
        self._seed_data()

        exported = self.store.export_bundle()

        self.assertIn("entries", exported)
        self.assertIn("fragments", exported)
        self.assertIn("templates", exported)
        self.assertEqual(exported["entries"][0]["id"], "entry_demo")
        self.assertEqual(exported["fragments"][0]["id"], "frag_demo")
        self.assertEqual(exported["templates"][0]["id"], "tpl_demo")

    def test_export_bundle_csv_contains_mixed_records(self):
        self._seed_data()

        csv_text = self.store.export_bundle_csv()
        rows = list(csv.DictReader(io.StringIO(csv_text)))

        self.assertEqual(len(rows), 3)
        self.assertEqual({row["record_type"] for row in rows}, {"entry", "fragment", "template"})
        entry_row = next(row for row in rows if row["record_type"] == "entry")
        self.assertEqual(entry_row["id"], "entry_demo")
        self.assertEqual(json.loads(entry_row["tags_json"]), ["portrait"])

    def test_import_bundle_merge_updates_entry_and_versions(self):
        self._seed_data()

        result = self.store.import_bundle(
            {
                "templates": [
                    {
                        "id": "tpl_demo",
                        "title": "模板A-已更新",
                        "ir": {"segments": [{"type": "literal", "text": "updated"}]},
                    }
                ],
                "fragments": [
                    {
                        "id": "frag_demo",
                        "title": "片段A-已更新",
                        "text": "soft light",
                        "tags": ["light", "soft"],
                        "model_scope": ["SDXL"],
                    }
                ],
                "entries": [
                    {
                        "id": "entry_demo",
                        "title": "记录A-已更新",
                        "template_id": "tpl_demo",
                        "tags": ["portrait", "updated"],
                        "model_scope": ["SDXL", "Flux"],
                        "variables": {"subject": "dog"},
                        "fragments": [{"id": "frag_demo", "weight": 1.2}],
                        "raw": {"positive": "new positive", "negative": "new negative"},
                        "params": {"steps": 40, "cfg": 8},
                    }
                ],
            },
            conflict_strategy="merge",
        )

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 3)
        entry = self.store.get_entry("entry_demo")
        self.assertEqual(entry["title"], "记录A-已更新")
        self.assertEqual(entry["variables"]["subject"], "dog")
        self.assertEqual(entry["version"], 2)
        versions = self.store.list_entry_versions("entry_demo")
        self.assertEqual(len(versions), 2)

    def test_import_csv_text_creates_all_record_types(self):
        self._seed_data()
        csv_text = self.store.export_bundle_csv()

        with tempfile.TemporaryDirectory() as other_dir:
            other_db_path = str(Path(other_dir) / "other.db")
            with mock.patch("promptvault.db.get_db_path", return_value=other_db_path):
                other_store = PromptVaultStore()
                result = other_store.import_csv_text(csv_text, conflict_strategy="merge")
                self.assertEqual(other_store.get_template("tpl_demo")["title"], "模板A")
                self.assertEqual(other_store.get_fragment("frag_demo")["text"], "cinematic lighting")
                self.assertEqual(other_store.get_entry("entry_demo")["variables"]["subject"], "cat")

        self.assertEqual(result["created"], 3)


if __name__ == "__main__":
    unittest.main()
