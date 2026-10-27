import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import pipeline


class NamedInputTests(unittest.TestCase):
    def test_off_by_default(self):
        with mock.patch.object(config, "NAMED_TRANSCRIPT", False):
            self.assertIsNone(pipeline.named_transcript_for_run(Path("/nowhere")))

    def test_on_uses_the_named_text(self):
        with mock.patch.object(config, "NAMED_TRANSCRIPT", True), \
                mock.patch("transcript_names.build_named_transcript",
                           return_value=("NAMED", {})):
            self.assertEqual(pipeline.named_transcript_for_run(Path("x")), "NAMED")

    def test_on_without_voice_data_falls_back(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(config, "NAMED_TRANSCRIPT", True):
            self.assertIsNone(pipeline.named_transcript_for_run(Path(folder)))

    def test_cleanup_reads_the_named_text_when_on(self):
        seen = []
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(pipeline, "named_transcript_for_run", return_value="NAMED"), \
                mock.patch.object(pipeline, "clean_transcript_in_chunks",
                                  side_effect=lambda text: seen.append(text) or text):
            pipeline.run_ai_cleanup(Path(folder), transcript="ORIGINAL")
        self.assertEqual(seen, ["NAMED"])

    def test_cleanup_unchanged_when_off(self):
        seen = []
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(pipeline, "named_transcript_for_run", return_value=None), \
                mock.patch.object(pipeline, "clean_transcript_in_chunks",
                                  side_effect=lambda text: seen.append(text) or text):
            pipeline.run_ai_cleanup(Path(folder), transcript="ORIGINAL")
        self.assertEqual(seen, ["ORIGINAL"])


if __name__ == "__main__":
    unittest.main()
