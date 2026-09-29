import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SetupSurfaceTests(unittest.TestCase):
    def test_swift_backend_reads_install_metadata(self):
        text = (
            ROOT
            / "swift"
            / "Meeting Transcriber"
            / "Meeting Transcriber"
            / "BackendService.swift"
        ).read_text(encoding="utf-8")

        self.assertIn('"install.json"', text)
        self.assertIn('"MEETING_TRANSCRIBER_PROJECT_DIR"', text)
        self.assertNotIn('/Users/\\(username)/Projects/meeting-transcriber', text)

    def test_bootstrap_does_not_pipe_downloaded_code_to_shell(self):
        text = (ROOT / "tools" / "setup" / "bootstrap_macos.sh").read_text(
            encoding="utf-8"
        )
        compact = text.replace(" ", "")
        self.assertNotIn("curl|bash", compact)
        self.assertNotIn("curl|sh", compact)
        self.assertIn("WHISPER_MODEL_URL=", text)
        self.assertIn("--dry-run", text)
        self.assertIn("--check", text)

    def test_bootstrap_dry_run_is_non_interactive(self):
        text = (ROOT / "tools" / "setup" / "bootstrap_macos.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--dry-run) DRY_RUN=1; NON_INTERACTIVE=1 ;;", text)

    def test_setup_has_one_user_configurable_meetings_recordings_path(self):
        bootstrap = (ROOT / "tools" / "setup" / "bootstrap_macos.sh").read_text(
            encoding="utf-8"
        )
        configure = (ROOT / "tools" / "setup" / "configure_install.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("--meetings-dir", bootstrap)
        self.assertNotIn('"meetings_dir"', configure)
        self.assertIn("--recordings-dir", bootstrap)

    def test_bootstrap_preserves_existing_settings_as_defaults(self):
        text = (ROOT / "tools" / "setup" / "bootstrap_macos.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('SETTINGS_PATH="$HOME/Library/Application Support/Meeting Transcriber/settings.json"', text)
        self.assertIn('existing_setting output_dir', text)
        self.assertIn('existing_setting archive_dir', text)
        self.assertIn('existing_setting recordings_dir', text)
        self.assertIn('existing_setting llm_model', text)
        self.assertIn('Current non-empty settings are preserved as setup defaults.', text)

    def test_bootstrap_uses_hardware_aware_fresh_model_default(self):
        text = (ROOT / "tools" / "setup" / "bootstrap_macos.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('fresh_model_default()', text)
        self.assertIn('sysctl -n hw.memsize', text)
        self.assertIn("qwen3:14b", text)
        self.assertIn("qwen3:8b", text)

    def test_bootstrap_prefers_functional_dependency_checks(self):
        text = (ROOT / "tools" / "setup" / "bootstrap_macos.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('command -v whisper-cli', text)
        self.assertIn('whisper-cli --help', text)
        self.assertIn('command -v ollama', text)
        self.assertIn('ollama --version', text)
        self.assertIn('Ollama model $LLM_MODEL already present; keeping it', text)

    def test_github_installer_uses_public_repository(self):
        text = (ROOT / "tools" / "setup" / "install_from_github.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("meeting-transcriber-public.git", text)
        self.assertIn("git clone", text)
        self.assertIn("git pull --ff-only", text)


if __name__ == "__main__":
    unittest.main()
