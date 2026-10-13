import json
import unittest
from unittest.mock import Mock

from llm_backend import OllamaBackend


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"response": "OK"}).encode("utf-8")


class OllamaBackendTimeoutTests(unittest.TestCase):
    def _make_backend(self, urlopen):
        return OllamaBackend(
            model="test-model",
            url="http://127.0.0.1:11434/api/generate",
            context_size=0,
            urlopen=urlopen,
        )

    def test_custom_timeout_is_forwarded_to_urlopen(self):
        urlopen = Mock(return_value=_FakeResponse())
        backend = self._make_backend(urlopen)

        result = backend.generate(
            "hello",
            timeout_seconds=240,
        )

        self.assertEqual(result, "OK")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 240.0)

    def test_default_timeout_remains_120_seconds(self):
        urlopen = Mock(return_value=_FakeResponse())
        backend = self._make_backend(urlopen)

        result = backend.generate("hello")

        self.assertEqual(result, "OK")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 120.0)

    def test_timeout_tests_never_use_real_network(self):
        urlopen = Mock(return_value=_FakeResponse())
        backend = self._make_backend(urlopen)

        backend.generate("hello")

        urlopen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
