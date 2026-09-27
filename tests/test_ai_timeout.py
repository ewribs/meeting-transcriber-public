import json
import unittest
from unittest.mock import patch

import ai


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"response": "OK"}).encode("utf-8")


class AskLlmTimeoutTests(unittest.TestCase):
    @patch("ai.urllib.request.urlopen")
    def test_custom_timeout_is_forwarded_to_urllib(self, urlopen):
        urlopen.return_value = _FakeResponse()

        result = ai.ask_llm(
            "hello",
            timeout_seconds=240,
        )

        self.assertEqual(result, "OK")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 240.0)

    @patch("ai.urllib.request.urlopen")
    def test_default_timeout_remains_120_seconds(self, urlopen):
        urlopen.return_value = _FakeResponse()

        result = ai.ask_llm("hello")

        self.assertEqual(result, "OK")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 120.0)


if __name__ == "__main__":
    unittest.main()
