import json
import unittest
from unittest.mock import patch

from llm_backend import (
    MLXBackend,
    OllamaBackend,
    create_backend,
    normalize_backend_name,
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


if __name__ == "__main__":
    unittest.main()
