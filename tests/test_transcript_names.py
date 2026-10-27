import tempfile
import unittest
from pathlib import Path
from unittest import mock

import transcript_names as tn
import voice_cli
import voice_service as vs


def voice(vid, turns, person=None, status=None, noise=None):
    item = {
        "id": vid,
        "seconds": sum(b - a for a, b in turns),
        "status": status or ("named" if person else "unknown"),
        "person_id": person.lower() if person else None,
        "person": person,
        "turns": [list(t) for t in turns],
    }
    if noise:
        item["noise"] = noise
    return item


def document(*voices):
    return {"version": vs.SPEAKERS_VERSION, "remote_silent": False,
            "voices": list(voices)}


class LabelForSpanTests(unittest.TestCase):
    def test_named_voice_names_the_line(self):
        doc = document(voice("SPEAKER_00", [(0, 10)], "Alex"))
        self.assertEqual(tn.label_for_span(2, 6, doc["voices"]), "Alex")

    def test_line_with_a_long_pause_still_gets_the_name(self):
        doc = document(voice("SPEAKER_00", [(5, 7)], "Alex"))
        self.assertEqual(tn.label_for_span(0, 20, doc["voices"]), "Alex")

    def test_no_voice_at_that_time_is_unidentified(self):
        doc = document(voice("SPEAKER_00", [(50, 60)], "Alex"))
        self.assertEqual(tn.label_for_span(0, 10, doc["voices"]), tn.UNIDENTIFIED)

    def test_a_brush_with_a_voice_is_not_enough(self):
        doc = document(voice("SPEAKER_00", [(9.9, 12)], "Alex"))
        self.assertEqual(tn.label_for_span(0, 10, doc["voices"]), tn.UNIDENTIFIED)

    def test_two_people_talking_over_each_other_is_unidentified(self):
        doc = document(voice("SPEAKER_00", [(0, 5)], "Alex"),
                       voice("SPEAKER_01", [(4, 9)], "Sam"))
        self.assertEqual(tn.label_for_span(0, 10, doc["voices"]), tn.UNIDENTIFIED)

    def test_the_main_voice_wins_over_a_short_interjection(self):
        doc = document(voice("SPEAKER_00", [(0, 9)], "Alex"),
                       voice("SPEAKER_01", [(9, 10)], "Sam"))
        self.assertEqual(tn.label_for_span(0, 10, doc["voices"]), "Alex")

    def test_unnamed_voice_is_unidentified(self):
        doc = document(voice("SPEAKER_00", [(0, 10)]))
        self.assertEqual(tn.label_for_span(0, 10, doc["voices"]), tn.UNIDENTIFIED)

    def test_too_short_voice_is_unidentified(self):
        doc = document(voice("SPEAKER_00", [(0, 10)], status="too_short"))
        self.assertEqual(tn.label_for_span(0, 10, doc["voices"]), tn.UNIDENTIFIED)

    def test_static_voice_is_never_named(self):
        doc = document(voice("SPEAKER_00", [(0, 10)], "Alex", noise="static"))
        self.assertEqual(tn.label_for_span(0, 10, doc["voices"]), tn.UNIDENTIFIED)

    def test_empty_span_is_unidentified(self):
        doc = document(voice("SPEAKER_00", [(0, 10)], "Alex"))
        self.assertEqual(tn.label_for_span(5, 5, doc["voices"]), tn.UNIDENTIFIED)


VTT_REMOTE = """WEBVTT

00:00:00.000 --> 00:00:05.000
 Hello there.

00:00:05.000 --> 00:00:10.000
 Thanks for joining.

00:00:20.000 --> 00:00:25.000
 What about the budget?
"""

VTT_MIC = """WEBVTT

00:00:11.000 --> 00:00:15.000
 Good to be here.
"""


def make_run(root, name="2026-01-01_0900_Sync", doc=None):
    run = Path(root) / name
    (run / "transcript").mkdir(parents=True)
    (run / "transcript" / "remote.vtt").write_text(VTT_REMOTE, encoding="utf-8")
    (run / "transcript" / "mic.vtt").write_text(VTT_MIC, encoding="utf-8")
    if doc is not None:
        vs.write_speakers(run, doc)
    return run


class BuildTests(unittest.TestCase):
    def test_lines_get_names_and_the_user_keeps_their_own(self):
        doc = document(voice("SPEAKER_00", [(0, 10)], "Alex"),
                       voice("SPEAKER_01", [(20, 25)]))
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp, doc=doc)
            text, counts = tn.build_named_transcript(run, "Pat")
        self.assertEqual(counts, {"Alex": 1, "Pat": 1, "Unidentified": 1})
        self.assertIn("**Alex**", text)
        self.assertIn("**Pat**", text)
        self.assertIn("**Unidentified**", text)
        self.assertNotIn("**Remote**", text)
        self.assertNotIn("**Mic**", text)

    def test_neighbouring_lines_by_the_same_person_are_joined(self):
        doc = document(voice("SPEAKER_00", [(0, 10)], "Alex"))
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp, doc=doc)
            text, _ = tn.build_named_transcript(run, "Pat")
        self.assertIn("Hello there. Thanks for joining.", text)

    def test_two_different_people_are_never_joined(self):
        doc = document(voice("SPEAKER_00", [(0, 5)], "Alex"),
                       voice("SPEAKER_01", [(5, 10)], "Sam"))
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp, doc=doc)
            text, counts = tn.build_named_transcript(run, "Pat")
        self.assertEqual(counts.get("Alex"), 1)
        self.assertEqual(counts.get("Sam"), 1)
        self.assertNotIn("Hello there. Thanks for joining.", text)

    def test_blank_self_name_falls_back_to_mic(self):
        doc = document(voice("SPEAKER_00", [(0, 10)], "Alex"))
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp, doc=doc)
            _, counts = tn.build_named_transcript(run, "")
        self.assertIn("Mic", counts)

    def test_no_voice_information_gives_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            with self.assertRaises(tn.TranscriptNamesError) as caught:
                tn.build_named_transcript(run, "Pat")
        self.assertIn("voice_cli.py identify", str(caught.exception))

    def test_missing_caption_files_give_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            vs.write_speakers(run, document(voice("SPEAKER_00", [(0, 10)], "Alex")))
            with self.assertRaises(tn.TranscriptNamesError):
                tn.build_named_transcript(run, "Pat")

    def test_the_original_transcript_is_left_alone(self):
        doc = document(voice("SPEAKER_00", [(0, 10)], "Alex"))
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp, doc=doc)
            original = run / "meeting_transcript.md"
            original.write_text("original", encoding="utf-8")
            path, _ = tn.write_named_transcript(run, "Pat")
            self.assertEqual(path.name, tn.NAMED_FILE)
            self.assertEqual(original.read_text(encoding="utf-8"), "original")
            self.assertTrue(path.exists())


class CommandTests(unittest.TestCase):
    def test_names_command_writes_the_file(self):
        doc = document(voice("SPEAKER_00", [(0, 10)], "Alex"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            out.mkdir()
            run = make_run(out, doc=doc)
            dirs = (out, Path(tmp) / "meetings", Path(tmp) / "archive")
            with mock.patch("config.SELF_NAME", "Pat"):
                code = voice_cli.main(["names", run.name], dirs=dirs,
                                      voices_dir=Path(tmp) / "voices")
            self.assertEqual(code, 0)
            self.assertIn("**Alex**",
                          (run / tn.NAMED_FILE).read_text(encoding="utf-8"))

    def test_names_command_explains_a_missing_voice_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            out.mkdir()
            run = make_run(out)
            dirs = (out, Path(tmp) / "meetings", Path(tmp) / "archive")
            code = voice_cli.main(["names", run.name], dirs=dirs,
                                  voices_dir=Path(tmp) / "voices")
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()


class SingleMicNamesTests(unittest.TestCase):
    def test_mic_lines_are_unidentified_when_remote_was_not_captured(self):
        from utils import TranscriptEntry
        import transcript_names as tn
        mic = [TranscriptEntry(0.0, 4.0, "Mic", "Hello from the speakerphone, everyone here.")]
        entries = tn.build_named_entries([], mic, {"voices": [], "remote_silent": True}, "Sam")
        self.assertEqual([e.speaker for e in entries], ["Unidentified"])
        entries = tn.build_named_entries([], [TranscriptEntry(0.0, 4.0, "Mic", "Hello from my desk, everyone here.")],
                                         {"voices": []}, "Sam")
        self.assertEqual([e.speaker for e in entries], ["Sam"])


class MicTrackNamesTests(unittest.TestCase):
    def test_mic_lines_get_the_name_of_the_voice(self):
        from utils import TranscriptEntry
        import transcript_names as tn
        document = {"track": "mic", "voices": [
            {"status": "named", "person": "Pat Lee", "turns": [[0.0, 10.0]]},
            {"status": "unknown", "turns": [[10.0, 20.0]]}]}
        mic = [TranscriptEntry(0.0, 8.0, "Mic", "Hello there, this is the first voice."),
               TranscriptEntry(11.0, 19.0, "Mic", "And this is another voice entirely.")]
        remote = [TranscriptEntry(0.0, 3.0, "Remote", "(static crackling)")]
        entries = tn.build_named_entries(remote, mic, document, "Sam")
        self.assertEqual([e.speaker for e in entries], ["Pat Lee", "Unidentified"])
