import subprocess
import unittest
from unittest.mock import patch

from ollama_models import (
    discover_installed_ollama_models,
    parse_ollama_list,
)


class OllamaModelTests(unittest.TestCase):
    def test_parse_ollama_list(self):
        output = """NAME            ID              SIZE      MODIFIED\nqwen3:8b        abc123          5.2 GB    2 days ago\nllama3.2:3b     def456          2.0 GB    1 week ago\n"""

        self.assertEqual(
            parse_ollama_list(output),
            ["qwen3:8b", "llama3.2:3b"],
        )

    def test_parse_deduplicates_models(self):
        output = """NAME ID SIZE MODIFIED\nqwen3:8b a 1 GB now\nqwen3:8b b 1 GB now\n"""

        self.assertEqual(
            parse_ollama_list(output),
            ["qwen3:8b"],
        )

    @patch("ollama_models.subprocess.run")
    def test_discovery_returns_models(self, run_mock):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["ollama", "list"],
            returncode=0,
            stdout=(
                "NAME ID SIZE MODIFIED\n"
                "qwen3:8b abc 5.2 GB now\n"
            ),
            stderr="",
        )

        models, error = (
            discover_installed_ollama_models()
        )

        self.assertEqual(models, ["qwen3:8b"])
        self.assertIsNone(error)

    @patch("ollama_models.subprocess.run")
    def test_discovery_handles_cli_failure(
        self,
        run_mock,
    ):
        run_mock.return_value = subprocess.CompletedProcess(
            args=["ollama", "list"],
            returncode=1,
            stdout="",
            stderr="Ollama is not running",
        )

        models, error = (
            discover_installed_ollama_models()
        )

        self.assertEqual(models, [])
        self.assertEqual(
            error,
            "Ollama is not running",
        )


if __name__ == "__main__":
    unittest.main()
