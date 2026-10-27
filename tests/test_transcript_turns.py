import json
import config
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import formatter
import transcript_turns as tt
from utils import TranscriptEntry


def entry(start, end, speaker, text):
    return TranscriptEntry(start=start, end=end, speaker=speaker, text=text)


VTT_REMOTE = """WEBVTT

00:00:00.000 --> 00:00:05.000
 Hello there.

00:00:05.000 --> 00:00:10.000
 Thanks for joining.

00:00:30.000 --> 00:00:33.000
 .
"""

VTT_MIC = """WEBVTT

00:00:11.000 --> 00:00:15.000
 Good to be here.
"""


def make_run(root, remote=VTT_REMOTE, mic=VTT_MIC, with_markdown=False):
    run = Path(root) / "2026-01-01_0900_Sync"
    (run / "transcript").mkdir(parents=True)
    (run / "transcript" / "remote.vtt").write_text(remote, encoding="utf-8")
    (run / "transcript" / "mic.vtt").write_text(mic, encoding="utf-8")
    if with_markdown:
        turns = tt.turns_from_run(run)
        (run / "meeting_transcript.md").write_text(tt.render_markdown(turns), encoding="utf-8")
    return run


class BuildTests(unittest.TestCase):
    def test_turns_follow_the_entries(self):
        entries = [entry(0, 5, "Remote", "Hi."), entry(6, 9, "Mic", "Hello.")]
        turns = tt.turns_from_entries(entries)
        self.assertEqual([t.id for t in turns], ["t0001", "t0002"])
        self.assertEqual([t.channel for t in turns], ["remote", "mic"])
        self.assertEqual(turns[1].start, 6.0)
        self.assertEqual(turns[0].text, turns[0].text_raw)
        self.assertIsNone(turns[0].speaker)

    def test_unknown_label_is_refused(self):
        with self.assertRaises(tt.TurnsError):
            tt.turns_from_entries([entry(0, 1, "Alex", "Hi.")])

    def test_lone_punctuation_is_dropped_and_neighbours_join(self):
        with tempfile.TemporaryDirectory() as tmp:
            turns = tt.turns_from_run(make_run(tmp))
        self.assertEqual([t.channel for t in turns], ["remote", "mic"])
        self.assertEqual(turns[0].text, "Hello there. Thanks for joining.")

    def test_missing_caption_files_give_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(tt.TurnsError):
                tt.turns_from_run(Path(tmp))


class RenderTests(unittest.TestCase):
    def test_rendering_matches_the_existing_formatter_exactly(self):
        entries = [entry(0, 5, "Remote", "Hi."), entry(62, 70, "Mic", "Hello."),
                   entry(3700, 3710, "Remote", "Late.")]
        expected = formatter.format_transcript(entries)
        self.assertEqual(tt.render_markdown(tt.turns_from_entries(entries)), expected)

    def test_cleaned_text_can_be_rendered_instead(self):
        turns = tt.turns_from_entries([entry(0, 5, "Remote", "um hi")])
        turns[0].text = "Hi."
        self.assertIn("Hi.", tt.render_markdown(turns, field="text"))
        self.assertIn("um hi", tt.render_markdown(turns))

    def test_bad_field_is_refused(self):
        with self.assertRaises(tt.TurnsError):
            tt.render_markdown([], field="speaker")


class SaveLoadTests(unittest.TestCase):
    def test_round_trip(self):
        turns = tt.turns_from_entries([entry(0.25, 5.5, "Remote", "Hi."), entry(6, 9, "Mic", "Yo.")])
        with tempfile.TemporaryDirectory() as tmp:
            tt.save_turns(Path(tmp), turns)
            self.assertEqual(tt.load_turns(Path(tmp)), turns)
            self.assertFalse((Path(tmp) / (tt.TURNS_FILE + ".tmp")).exists())

    def test_no_file_means_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(tt.load_turns(Path(tmp)))

    def test_damaged_file_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / tt.TURNS_FILE).write_text("{not json", encoding="utf-8")
            with self.assertRaises(tt.TurnsError):
                tt.load_turns(Path(tmp))

    def test_other_version_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / tt.TURNS_FILE).write_text(json.dumps({"version": 99, "turns": []}), encoding="utf-8")
            with self.assertRaises(tt.TurnsError):
                tt.load_turns(Path(tmp))

    def test_wrong_shape_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / tt.TURNS_FILE).write_text(
                json.dumps({"version": 1, "turns": [{"id": "t1"}]}), encoding="utf-8")
            with self.assertRaises(tt.TurnsError):
                tt.load_turns(Path(tmp))

    def test_saving_inside_transcription_never_raises(self):
        entries = [entry(0, 5, "Remote", "Hi.")]
        self.assertFalse(tt.save_turns_safely(Path("/nonexistent/folder/for/test"), entries))
        self.assertFalse(tt.save_turns_safely(Path("/tmp"), [entry(0, 1, "Alex", "Hi.")]))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(tt.save_turns_safely(Path(tmp), entries))


class CompareTests(unittest.TestCase):
    def test_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp, with_markdown=True)
            self.assertEqual(tt.compare_with_saved(run), "same")

    def test_older_transcript_with_noise_lines_is_recognised(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp, with_markdown=True)
            saved = (run / "meeting_transcript.md").read_text(encoding="utf-8")
            (run / "meeting_transcript.md").write_text(
                saved + "\n[00:30] **Remote**\n\n.\n\n", encoding="utf-8")
            self.assertEqual(tt.compare_with_saved(run), "older")

    def test_a_real_difference_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp, with_markdown=True)
            saved = (run / "meeting_transcript.md").read_text(encoding="utf-8")
            (run / "meeting_transcript.md").write_text(
                saved.replace("Thanks for joining.", "Something else entirely."), encoding="utf-8")
            self.assertEqual(tt.compare_with_saved(run), "different")

    def test_no_saved_transcript_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(tt.compare_with_saved(make_run(tmp)), "skipped")


class CommandTests(unittest.TestCase):
    def test_build_writes_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(tmp)
            code = tt.main(["build", run.name, "--output-dir", tmp])
            self.assertEqual(code, 0)
            self.assertEqual(len(tt.load_turns(run)), 2)

    def test_check_reports_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_run(tmp, with_markdown=True)
            self.assertEqual(tt.main(["check", "--output-dir", tmp]), 0)


if __name__ == "__main__":
    unittest.main()


class NamedTurnsTests(unittest.TestCase):
    def entries(self):
        from utils import TranscriptEntry
        remote = [TranscriptEntry(0.0, 4.0, "Remote", "Hello there everyone."),
                  TranscriptEntry(4.5, 8.0, "Remote", "Thanks for joining today."),
                  TranscriptEntry(20.0, 24.0, "Remote", "Who is this speaking now?")]
        mic = [TranscriptEntry(9.0, 12.0, "Mic", "Glad to be here.")]
        document = {"voices": [
            {"status": "named", "person": "Pat Lee", "turns": [[0.0, 8.0]]},
            {"status": "unknown", "turns": [[20.0, 24.0]]}]}
        return remote, mic, document

    def test_every_turn_gets_a_speaker_record(self):
        turns = tt.build_named_turns(*self.entries())
        self.assertEqual([t.speaker for t in turns], [
            {"kind": "person", "name": "Pat Lee"}, {"kind": "self"},
            {"kind": "unidentified"}])
        self.assertEqual([t.channel for t in turns], ["remote", "mic", "remote"])
        self.assertEqual([t.id for t in turns], ["t0001", "t0002", "t0003"])

    def test_names_are_shown_in_the_rendering(self):
        turns = tt.build_named_turns(*self.entries())
        text = tt.render_named_markdown(turns, "Sam")
        self.assertIn("**Pat Lee**", text)
        self.assertIn("**Sam**", text)
        self.assertIn("**Unidentified**", text)
        self.assertNotIn("**Remote**", text)


class SingleMicTests(unittest.TestCase):
    def test_nothing_is_credited_to_the_user_when_remote_was_not_captured(self):
        from utils import TranscriptEntry
        mic = [TranscriptEntry(0.0, 4.0, "Mic", "I will send the file. Sure, Riley will call you.")]
        turns = tt.build_named_turns([], mic, {"voices": [], "remote_silent": True})
        self.assertEqual([t.speaker for t in turns], [{"kind": "unidentified"}])
        self.assertEqual([t.channel for t in turns], ["mic"])

    def test_normal_meetings_still_credit_the_user(self):
        from utils import TranscriptEntry
        mic = [TranscriptEntry(0.0, 4.0, "Mic", "I will send the file.")]
        turns = tt.build_named_turns([], mic, {"voices": []})
        self.assertEqual([t.speaker for t in turns], [{"kind": "self"}])


class MicTrackVoicesTests(unittest.TestCase):
    DOCUMENT = {"track": "mic", "voices": [
        {"status": "named", "person": "Sam", "turns": [[0.0, 10.0]]},
        {"status": "unknown", "turns": [[10.0, 20.0]]}]}

    def entries(self):
        from utils import TranscriptEntry
        mic = [TranscriptEntry(0.0, 8.0, "Mic", "I will send the file tomorrow morning."),
               TranscriptEntry(11.0, 19.0, "Mic", "Sounds good, thanks for doing that.")]
        remote = [TranscriptEntry(0.0, 3.0, "Remote", "(static crackling)")]
        return remote, mic

    def test_mic_lines_are_named_by_voice_and_the_hum_is_dropped(self):
        remote, mic = self.entries()
        with mock.patch.object(config, "SELF_NAME", "Sam"):
            turns = tt.build_named_turns(remote, mic, self.DOCUMENT)
        self.assertEqual([t.speaker for t in turns], [{"kind": "self"}, {"kind": "unidentified"}])
        self.assertEqual([t.channel for t in turns], ["mic", "mic"])
        self.assertNotIn("static", " ".join(t.text for t in turns))

    def test_another_named_voice_is_a_person(self):
        from utils import TranscriptEntry
        document = {"track": "mic", "voices": [
            {"status": "named", "person": "Pat Lee", "turns": [[0.0, 10.0]]}]}
        mic = [TranscriptEntry(0.0, 8.0, "Mic", "I will send the file tomorrow morning.")]
        turns = tt.build_named_turns([], mic, document)
        self.assertEqual(turns[0].speaker, {"kind": "person", "name": "Pat Lee"})
