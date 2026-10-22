import tempfile
import unittest
from pathlib import Path

import voice_sources as vsrc


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


class NameTests(unittest.TestCase):
    def test_common_patterns(self):
        cases = {
            "Alex1v1092126.m4a": "alex",
            "1v1Sam092826.m4a": "sam",
            "Pat 1v1100526.m4a": "pat",
            "Lee1v1Catchup100226.m4a": "lee",
            "AlexK1v1092126.m4a": "alexk",
            "Alexk1v1101426.m4a": "alexk",
            "Alex1V1092126.M4A": "alex",
        }
        for name, expected in cases.items():
            self.assertEqual(vsrc.person_from_filename(name), expected, name)

    def test_group_meetings_are_not_one_on_ones(self):
        for name in ("TeamHuddleAlexSam092426.m4a", "Review102026.m4a", ".m4a"):
            self.assertIsNone(vsrc.person_from_filename(name), name)


class DisplayNameTests(unittest.TestCase):
    def test_keeps_the_way_it_is_written(self):
        self.assertEqual(vsrc.display_name("Alex1v1092126.m4a"), "Alex")
        self.assertEqual(vsrc.display_name("1v1Sam092826.m4a"), "Sam")
        self.assertEqual(vsrc.display_name("AlexK1v1092126.m4a"), "AlexK")
        self.assertEqual(vsrc.display_name("alex1v1092126.m4a"), "Alex")


class FindTests(unittest.TestCase):
    def test_groups_by_person_and_merges_spelling_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("AlexK1v1092126.m4a", "Alexk1v1101426.m4a",
                         "Sam1v1100526.m4a", "Team102026.m4a"):
                touch(root / name)
            found = vsrc.find_recordings([root])
            self.assertEqual(sorted(found), ["alexk", "sam"])
            self.assertEqual(len(found["alexk"]), 2)

    def test_exclude_text_skips_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root / "Alex1v1092126.m4a")
            touch(root / "Alex1v109212614B.m4a")
            found = vsrc.find_recordings([root], exclude=["14b"])
            self.assertEqual([p.name for p in found["alex"]], ["Alex1v1092126.m4a"])

    def test_archive_layout_and_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch(root / "meetings" / "Alex1v1100526.m4a")
            touch(root / "archive" / "2026-10-05_1000_Alex1v1100526" / "source" / "Alex1v1100526.m4a")
            touch(root / "archive" / "2026-08-19_1000_Alex1v1081926" / "source" / "Alex1v1081926.m4a")
            found = vsrc.find_recordings([root / "meetings"], [root / "archive"])
            names = sorted(p.name for p in found["alex"])
            self.assertEqual(names, ["Alex1v1081926.m4a", "Alex1v1100526.m4a"])
            local = [p for p in found["alex"] if p.name == "Alex1v1100526.m4a"][0]
            self.assertEqual(local.parent.name, "meetings")

    def test_missing_folders_are_ignored(self):
        self.assertEqual(vsrc.find_recordings([Path("/no/such/dir")], [Path("/no/other")]), {})


class ResolveAudioTests(unittest.TestCase):
    def test_priority_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "output" / "2026-10-20_1353_SomeMeeting102026"
            meetings = root / "meetings"
            touch(meetings / "SomeMeeting102026.m4a")
            self.assertEqual(
                vsrc.resolve_audio(run, meetings),
                meetings / "SomeMeeting102026.m4a",
            )
            archived = touch(run / "source" / "SomeMeeting102026.m4a")
            self.assertEqual(vsrc.resolve_audio(run, meetings), archived)
            remote = touch(run / "audio" / "remote.wav")
            self.assertEqual(vsrc.resolve_audio(run, meetings), remote)
            override = touch(root / "other.wav")
            self.assertEqual(vsrc.resolve_audio(run, meetings, override), override)

    def test_falls_back_to_the_archive_copy_after_local_audio_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "output" / "2026-08-20_1046_SomeMeeting082026"
            run.mkdir(parents=True)
            archive = root / "archive"
            kept = touch(archive / run.name / "source" / "SomeMeeting082026.m4a")
            self.assertEqual(vsrc.resolve_audio(run, root / "meetings", None, archive), kept)
            local = touch(root / "meetings" / "SomeMeeting082026.m4a")
            self.assertEqual(vsrc.resolve_audio(run, root / "meetings", None, archive), local)

    def test_nothing_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "2026-10-20_1353_X"
            run.mkdir()
            self.assertIsNone(vsrc.resolve_audio(run, Path(tmp) / "meetings"))
            self.assertIsNone(vsrc.resolve_audio(run, None, Path(tmp) / "missing.wav"))

    def test_run_name_suffix(self):
        self.assertEqual(vsrc.recording_suffix("2026-10-20_1353_Some_Meeting"), "Some_Meeting")
        self.assertEqual(vsrc.recording_suffix("plain"), "plain")


if __name__ == "__main__":
    unittest.main()


class ClipTests(unittest.TestCase):
    def test_window_comes_from_longest_turn_and_is_centered(self):
        from voice_sources import pick_clip_window
        start, length = pick_clip_window([[0, 5], [10, 40]], seconds=10)
        self.assertEqual(length, 10)
        self.assertAlmostEqual(start, 20.0)

    def test_short_turns_give_no_clip(self):
        from voice_sources import pick_clip_window
        self.assertIsNone(pick_clip_window([[0, 2], [5, 7]]))
        self.assertIsNone(pick_clip_window([]))

    def test_command_uses_channel_zero_for_m4a_only(self):
        from pathlib import Path
        from voice_sources import clip_command
        m4a = clip_command(Path("a.m4a"), 1, 2, Path("o.wav"))
        wav = clip_command(Path("remote.wav"), 1, 2, Path("o.wav"))
        self.assertIn("[0:a]pan=mono|c0=c0[out]", m4a)
        self.assertNotIn("-filter_complex", wav)
        self.assertGreater(m4a.index("-ss"), m4a.index("-i"))

    def test_make_clip_calls_runner(self):
        import tempfile
        from pathlib import Path
        from voice_sources import make_clip
        calls = []
        with tempfile.TemporaryDirectory() as d:
            out = make_clip(Path("a.m4a"), 1, 2, Path(d) / "x" / "o.wav",
                            runner=lambda cmd, **kw: calls.append(cmd))
            self.assertEqual(len(calls), 1)
            self.assertTrue(out.parent.exists())

    def test_safe_name(self):
        from voice_sources import safe_name
        self.assertEqual(safe_name("Sky 1v1 / Q3"), "Sky_1v1_Q3")


class ClipWindowsTests(unittest.TestCase):
    def test_several_clips_from_different_long_turns(self):
        turns = [[0, 5], [10, 30], [40, 52], [60, 63]]
        windows = vsrc.pick_clip_windows(turns, 2)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows, sorted(windows))
        self.assertEqual(windows[0], (15.0, 10.0))
        self.assertEqual(windows[1], (41.0, 10.0))

    def test_short_turns_are_skipped(self):
        self.assertEqual(vsrc.pick_clip_windows([[0, 2]], 3), [])
