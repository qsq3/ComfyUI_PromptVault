import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.modules.setdefault(
    "httpx",
    types.SimpleNamespace(
        AsyncHTTPTransport=object,
        AsyncClient=object,
        ConnectError=Exception,
    ),
)

from ComfyUI_PromptVault import nodes


class _FakeStore:
    def __init__(self):
        self.payload = None

    def create_entry(self, payload):
        self.payload = payload
        return {"id": "entry_test"}


class PromptVaultSaveNodeTests(unittest.TestCase):
    def setUp(self):
        self.store = _FakeStore()
        self.node = nodes.PromptVaultSaveNode()

    def test_input_types_expose_llm_generate_names(self):
        optional = self.node.INPUT_TYPES()["optional"]

        self.assertIn("llm_generate", optional)
        self.assertIn("llm_generate_mode", optional)
        self.assertNotIn("auto_generate", optional)
        self.assertNotIn("auto_generate_mode", optional)

    def test_save_node_prefers_explicit_positive_and_negative_inputs(self):
        with patch.object(nodes, "_make_thumbnail_png", return_value=(b"png", 256, 128)):
            with patch.object(nodes, "_extract_prompt_from_pnginfo", return_value=None):
                with patch.object(
                    nodes,
                    "_extract_generation_data",
                    return_value={"positive": "from metadata", "negative": "metadata neg"},
                ):
                    with patch.object(nodes, "_extract_from_workflow", return_value={}):
                        with patch.object(nodes, "_extract_generation_data_from_pnginfo", return_value={}):
                            with patch.object(nodes, "_extract_from_source_image_metadata", return_value=({}, [])):
                                with patch.object(nodes, "_debug_dump_png_meta", return_value=None):
                                    with patch.object(nodes.PromptVaultStore, "get", return_value=self.store):
                                        entry_id, status = self.node.run(
                                            image=object(),
                                            title="",
                                            tags="",
                                            model="",
                                            positive_prompt="manual positive",
                                            negative_prompt="manual negative",
                                            auto_generate=False,
                                            auto_generate_mode="auto",
                                            prompt=None,
                                            extra_pnginfo=None,
                                        )

        self.assertEqual(entry_id, "entry_test")
        self.assertIn("保存成功", status)
        self.assertEqual(self.store.payload["raw"]["positive"], "manual positive")
        self.assertEqual(self.store.payload["raw"]["negative"], "manual negative")

    def test_save_node_falls_back_to_extracted_prompts_when_optional_inputs_are_empty(self):
        with patch.object(nodes, "_make_thumbnail_png", return_value=(b"png", 256, 128)):
            with patch.object(nodes, "_extract_prompt_from_pnginfo", return_value=None):
                with patch.object(
                    nodes,
                    "_extract_generation_data",
                    return_value={"positive": "from metadata", "negative": "metadata neg"},
                ):
                    with patch.object(nodes, "_extract_from_workflow", return_value={}):
                        with patch.object(nodes, "_extract_generation_data_from_pnginfo", return_value={}):
                            with patch.object(nodes, "_extract_from_source_image_metadata", return_value=({}, [])):
                                with patch.object(nodes, "_debug_dump_png_meta", return_value=None):
                                    with patch.object(nodes.PromptVaultStore, "get", return_value=self.store):
                                        entry_id, status = self.node.run(
                                            image=object(),
                                            title="",
                                            tags="",
                                            model="",
                                            positive_prompt="",
                                            negative_prompt="",
                                            auto_generate=False,
                                            auto_generate_mode="auto",
                                            prompt=None,
                                            extra_pnginfo=None,
                                        )

        self.assertEqual(entry_id, "entry_test")
        self.assertIn("保存成功", status)
        self.assertEqual(self.store.payload["raw"]["positive"], "from metadata")
        self.assertEqual(self.store.payload["raw"]["negative"], "metadata neg")

    def test_save_node_uses_llm_generate_arguments(self):
        with patch.object(nodes, "_make_thumbnail_png", return_value=(b"png", 256, 128)):
            with patch.object(nodes, "_extract_prompt_from_pnginfo", return_value=None):
                with patch.object(
                    nodes,
                    "_extract_generation_data",
                    return_value={"positive": "from metadata", "negative": "metadata neg"},
                ):
                    with patch.object(nodes, "_extract_from_workflow", return_value={}):
                        with patch.object(nodes, "_extract_generation_data_from_pnginfo", return_value={}):
                            with patch.object(nodes, "_extract_from_source_image_metadata", return_value=({}, [])):
                                with patch.object(nodes, "_debug_dump_png_meta", return_value=None):
                                    with patch.object(
                                        nodes,
                                        "_maybe_auto_fill_with_llm",
                                        return_value=("final title", ["tag1"], True),
                                    ) as llm_mock:
                                        with patch.object(nodes.PromptVaultStore, "get", return_value=self.store):
                                            self.node.run(
                                                image=object(),
                                                title="",
                                                tags="",
                                                model="",
                                                positive_prompt="manual positive",
                                                negative_prompt="manual negative",
                                                llm_generate=True,
                                                llm_generate_mode="title_only",
                                                prompt=None,
                                                extra_pnginfo=None,
                                            )

        args = llm_mock.call_args.args
        self.assertEqual(args[0], "")
        self.assertEqual(args[1], [])
        self.assertEqual(args[2], "manual positive")
        self.assertEqual(args[3], "manual negative")
        self.assertTrue(args[4])
        self.assertEqual(args[5], "title_only")


if __name__ == "__main__":
    unittest.main()
