import types
import sys
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
    def get_llm_config(self):
        return {"enabled": True}


class _FakeLLMClient:
    def __init__(self, _config):
        self.auto_title_called = False

    async def test_connection(self):
        raise AssertionError("test_connection should not be called during save autofill")

    async def auto_title(self, positive, negative, existing_title="", existing_tags=None):
        self.auto_title_called = True
        self.last_args = {
            "positive": positive,
            "negative": negative,
            "existing_title": existing_title,
            "existing_tags": existing_tags or [],
        }
        return "AI标题"


class AutoFillWithLLMTests(unittest.TestCase):
    def test_auto_fill_calls_generation_directly_without_preflight_probe(self):
        with patch.object(nodes.PromptVaultStore, "get", return_value=_FakeStore()):
            with patch.object(nodes, "LLMClient", _FakeLLMClient):
                title, tags, changed = nodes._maybe_auto_fill_with_llm(
                    title="",
                    tags=[],
                    positive="prompt",
                    negative="",
                    auto_generate=True,
                    auto_generate_mode="title_only",
                )

        self.assertEqual(title, "AI标题")
        self.assertEqual(tags, [])
        self.assertTrue(changed)


if __name__ == "__main__":
    unittest.main()
