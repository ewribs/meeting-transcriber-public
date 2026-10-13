import json
import sys
import types
import unittest
from unittest.mock import patch

from llm_backend import (
    MLXBackend,
    OllamaBackend,
    create_backend,
    normalize_backend_name,
    normalize_backend_preference,
    resolve_backend_preference,
)


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class LLMBackendTests(unittest.TestCase):
    def test_backend_name_defaults_to_ollama(self):
        self.assertEqual(normalize_backend_name(None), "ollama")
        self.assertEqual(normalize_backend_name("unknown"), "ollama")
        self.assertEqual(normalize_backend_name("MLX-LM"), "mlx")


    def test_backend_preference_defaults_to_auto(self):
        self.assertEqual(normalize_backend_preference(None), "auto")
        self.assertEqual(normalize_backend_preference("unknown"), "auto")
        self.assertEqual(normalize_backend_preference("Ollama"), "ollama")
        self.assertEqual(normalize_backend_preference("MLX-LM"), "mlx")

    def test_auto_selects_mlx_on_high_memory_apple_silicon(self):
        hardware = type(
            "Hardware",
            (),
            {
                "system": "Darwin",
                "architecture": "arm64",
                "memory_gb": 36,
            },
        )()

        resolved = resolve_backend_preference(
            "auto",
            hardware=hardware,
            mlx_available=True,
        )

        self.assertEqual(resolved.resolved_name, "mlx")
        self.assertTrue(resolved.auto_eligible)

    def test_auto_keeps_ollama_on_lower_memory_mac(self):
        hardware = type(
            "Hardware",
            (),
            {
                "system": "Darwin",
                "architecture": "arm64",
                "memory_gb": 16,
            },
        )()

        resolved = resolve_backend_preference(
            "auto",
            hardware=hardware,
            mlx_available=True,
        )

        self.assertEqual(resolved.resolved_name, "ollama")
        self.assertFalse(resolved.auto_eligible)

    def test_auto_falls_back_to_ollama_when_mlx_runtime_missing(self):
        hardware = type(
            "Hardware",
            (),
            {
                "system": "Darwin",
                "architecture": "arm64",
                "memory_gb": 48,
            },
        )()

        resolved = resolve_backend_preference(
            "auto",
            hardware=hardware,
            mlx_available=False,
        )

        self.assertEqual(resolved.resolved_name, "ollama")
        self.assertTrue(resolved.auto_eligible)
        self.assertIn("not installed", resolved.reason)

    def test_manual_backend_override_is_preserved(self):
        hardware = type(
            "Hardware",
            (),
            {
                "system": "Darwin",
                "architecture": "arm64",
                "memory_gb": 64,
            },
        )()

        ollama = resolve_backend_preference(
            "ollama", hardware=hardware, mlx_available=True
        )
        mlx = resolve_backend_preference(
            "mlx", hardware=hardware, mlx_available=False
        )

        self.assertEqual(ollama.resolved_name, "ollama")
        self.assertEqual(mlx.resolved_name, "mlx")

    def test_create_backend_keeps_ollama_as_default_path(self):
        backend = create_backend(
            "ollama",
            ollama_model="model-a",
            ollama_url="http://localhost/test",
            context_size=4096,
            mlx_model="model-b",
            mlx_max_tokens=1000,
        )
        self.assertIsInstance(backend, OllamaBackend)
        self.assertEqual(backend.model, "model-a")

    def test_create_backend_can_select_mlx_without_loading_model(self):
        backend = create_backend(
            "mlx",
            ollama_model="model-a",
            ollama_url="http://localhost/test",
            context_size=4096,
            mlx_model="model-b",
            mlx_max_tokens=1000,
        )
        self.assertIsInstance(backend, MLXBackend)
        self.assertEqual(backend.model_name, "model-b")
        self.assertIsNone(backend._model)

    def test_ollama_backend_forwards_timeout_and_structured_format(self):
        calls = []

        def fake_urlopen(request, *, timeout):
            calls.append((request, timeout))
            return _FakeResponse({"response": "ok"})

        backend = OllamaBackend(
            model="model-a",
            url="http://localhost/test",
            context_size=4096,
            urlopen=fake_urlopen,
        )
        schema = {"type": "object", "properties": {"value": {"type": "string"}}}
        result = backend.generate("hello", response_format=schema, timeout_seconds=240)

        self.assertEqual(result, "ok")
        self.assertEqual(calls[0][1], 240.0)
        payload = json.loads(calls[0][0].data.decode("utf-8"))
        self.assertEqual(payload["model"], "model-a")
        self.assertEqual(payload["format"], schema)
        self.assertEqual(payload["options"]["num_ctx"], 4096)
        self.assertFalse(payload["think"])

    def test_mlx_uses_smaller_structured_generation_budget(self):
        calls = []

        def fake_generate(*args, **kwargs):
            calls.append(kwargs["max_tokens"])
            return '{"value":"ok"}'

        fake_module = types.SimpleNamespace(generate=fake_generate)
        backend = MLXBackend(model="model-b", max_tokens=8000)
        backend._model = object()

        class FakeTokenizer:
            def apply_chat_template(self, messages, **kwargs):
                return "prompt"

            def encode(self, text):
                return text.split()

        backend._tokenizer = FakeTokenizer()
        schema = {"type": "object", "properties": {"value": {"type": "string"}}}

        with patch.dict(sys.modules, {"mlx_lm": fake_module}):
            result = backend.generate("hello", response_format=schema)

        self.assertEqual(json.loads(result), {"value": "ok"})
        self.assertEqual(calls, [4000])

    def test_mlx_uses_full_budget_for_narrative_generation(self):
        calls = []

        def fake_generate(*args, **kwargs):
            calls.append(kwargs["max_tokens"])
            return "Narrative response"

        fake_module = types.SimpleNamespace(generate=fake_generate)
        backend = MLXBackend(model="model-b", max_tokens=8000)
        backend._model = object()

        class FakeTokenizer:
            def apply_chat_template(self, messages, **kwargs):
                return "prompt"

            def encode(self, text):
                return text.split()

        backend._tokenizer = FakeTokenizer()

        with patch.dict(sys.modules, {"mlx_lm": fake_module}):
            result = backend.generate("hello")

        self.assertEqual(result, "Narrative response")
        self.assertEqual(calls, [8000])


if __name__ == "__main__":
    unittest.main()
