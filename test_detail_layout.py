import unittest
from pathlib import Path


class PromptVaultDetailLayoutTests(unittest.TestCase):
    def test_render_detail_uses_top_row_summary_layout(self):
        js = Path("web/comfyui/promptvault.js").read_text(encoding="utf-8")

        self.assertIn('class: "pv-detail-top-row"', js)
        self.assertIn('class: "pv-detail-top-right"', js)
        self.assertIn('class: "pv-detail-header-row"', js)
        self.assertIn("targetBody.appendChild(topRow);", js)
        self.assertIn("      detailActions,", js)
        self.assertNotIn("命中原因:", js)
        self.assertNotIn('{ k1: "收藏"', js)
        self.assertNotIn('k2: "评分"', js)
        self.assertNotIn('const idLine = create("div", { class: "pv-detail-meta-line", text: `ID: ${entry.id || ""}` });', js)
        self.assertIn('const tableRows = [\n      ["ID", entry.id || ""],', js)
        self.assertIn('      ["模型", detailModelText],', js)
        self.assertIn('          create("td", { text: v, colspan: "3" }),', js)
        self.assertNotIn('create("div", { class: "pv-detail-meta-line", text: `模型: ${detailModelText}` })', js)
        self.assertIn('create("div", { class: "pv-detail-meta-line", text: `版本: v${entry.version || 1} · 状态: ${detailStatusText}` })', js)
        self.assertIn('create("div", { class: "pv-detail-meta-line", text: detailUpdatedText })', js)

    def test_detail_thumbnail_uses_contain_without_forced_ratio(self):
        css = Path("web/comfyui/promptvault.css").read_text(encoding="utf-8")
        thumb_block = css.split(".pv-thumb {", 1)[1].split("}", 1)[0]

        self.assertIn("object-fit: contain;", thumb_block)
        self.assertNotIn("object-fit: cover;", thumb_block)
        self.assertNotIn("aspect-ratio: 4 / 5;", thumb_block)


if __name__ == "__main__":
    unittest.main()
