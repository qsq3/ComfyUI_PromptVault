import tempfile
import unittest
from pathlib import Path
from unittest import mock

from promptvault.db import PromptVaultStore


class PromptVaultCardSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "promptvault.db")
        patcher = mock.patch("promptvault.db.get_db_path", return_value=self.db_path)
        self.addCleanup(patcher.stop)
        patcher.start()
        self.store = PromptVaultStore()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_entry(self, entry_id, title, positive, **extra):
        payload = {
            "id": entry_id,
            "title": title,
            "tags": extra.pop("tags", []),
            "model_scope": extra.pop("model_scope", []),
            "raw": {
                "positive": positive,
                "negative": extra.pop("negative", ""),
            },
            "variables": extra.pop("variables", {}),
            "params": extra.pop("params", {}),
        }
        payload.update(extra)
        return self.store.create_entry(payload)

    def test_search_entries_returns_card_summary_fields(self):
        self._create_entry(
            "entry_card",
            "人像卡片",
            "cinematic portrait lighting with warm tone and dramatic background",
            tags=["portrait", "warm"],
        )

        items = self.store.search_entries(limit=10)

        self.assertEqual(len(items), 1)
        self.assertIn("favorite", items[0])
        self.assertIn("score", items[0])
        self.assertIn("positive_preview", items[0])
        self.assertIn("has_thumbnail", items[0])
        self.assertTrue(items[0]["positive_preview"].startswith("cinematic portrait"))

    def test_search_entries_supports_favorite_filter_and_score_sort(self):
        low = self._create_entry(
            "entry_low",
            "低分记录",
            "simple portrait",
            tags=["portrait"],
        )
        high = self._create_entry(
            "entry_high",
            "高分收藏记录",
            "best quality portrait close-up",
            tags=["portrait", "favorite"],
        )

        self.store.update_entry(low["id"], {"score": 2.5, "favorite": 0})
        self.store.update_entry(high["id"], {"score": 9.1, "favorite": 1})

        items = self.store.search_entries(sort="score_desc", favorite_only=True)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "entry_high")
        self.assertEqual(items[0]["favorite"], 1)
        self.assertAlmostEqual(items[0]["score"], 9.1)

    def test_search_entries_supports_thumbnail_filter(self):
        self._create_entry("entry_no_thumb", "无图记录", "portrait no thumbnail")
        self._create_entry(
            "entry_thumb",
            "有图记录",
            "portrait with thumbnail",
            thumbnail_png=b"fakepngbytes",
            thumbnail_width=64,
            thumbnail_height=64,
        )

        items = self.store.search_entries(has_thumbnail=True)

        self.assertEqual([item["id"] for item in items], ["entry_thumb"])

    def test_search_entries_reports_match_reasons(self):
        self._create_entry(
            "entry_match",
            "Portrait 主图",
            "portrait close-up with cinematic light",
            tags=["portrait", "studio"],
        )

        items = self.store.search_entries(q="portrait")

        self.assertEqual(len(items), 1)
        self.assertIn("match_reasons", items[0])
        self.assertTrue(items[0]["match_reasons"])


    def test_search_entries_falls_back_for_single_chinese_character(self):
        self._create_entry(
            "entry_cn",
            "少女肖像",
            "年轻女人，电影光影，细节丰富",
            tags=["人像"],
        )

        items = self.store.search_entries(q="女")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "entry_cn")


if __name__ == "__main__":
    unittest.main()
