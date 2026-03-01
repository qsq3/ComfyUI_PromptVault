import unittest
from pathlib import Path


class PromptVaultPaginationUiTests(unittest.TestCase):
    def test_promptvault_js_defines_pagination_helpers_once(self):
        js = Path("web/comfyui/promptvault.js").read_text(encoding="utf-8")

        update_defs = js.count("function updatePaginationUI(") + js.count("updatePaginationUI = function (")
        refresh_defs = js.count("function refreshQuickFilterUI(") + js.count("refreshQuickFilterUI = function ()")

        self.assertEqual(update_defs, 1, "promptvault.js should define updatePaginationUI exactly once")
        self.assertEqual(refresh_defs, 1, "promptvault.js should define refreshQuickFilterUI exactly once")


if __name__ == "__main__":
    unittest.main()
