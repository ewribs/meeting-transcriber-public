import unittest

import voice_participants as vpart


def doc(*voices, silent=False):
    return {"remote_silent": silent, "voices": [
        {"id": f"V{i}", "status": status, "person": person, "seconds": seconds}
        for i, (status, person, seconds) in enumerate(voices)]}


def meta(*names):
    return {"participants": [{"name": n} for n in names]}


class SamePersonTests(unittest.TestCase):
    def test_case_spaces_and_prefix(self):
        self.assertTrue(vpart.same_person("Sam", "sam"))
        self.assertTrue(vpart.same_person("Sam K", "SamK"))
        self.assertTrue(vpart.same_person("Dana", "DanaQ"))
        self.assertTrue(vpart.same_person("Maryanne", "Maryann"))

    def test_different_people_do_not_match(self):
        self.assertFalse(vpart.same_person("Sam", "Pat"))
        self.assertFalse(vpart.same_person("", "Pat"))


class CompareTests(unittest.TestCase):
    def test_agree_text_only_and_voice_only(self):
        c = vpart.compare(
            "run",
            meta("Ava", "Mentioned"),
            doc(("named", "Ava", 300), ("named", "Spoke", 120), ("unknown", None, 90)),
        )
        self.assertEqual(c.both, ["Ava"])
        self.assertEqual(c.text_only, ["Mentioned"])
        self.assertEqual(c.voice_only, ["Spoke"])
        self.assertEqual(c.unnamed_voices, 1)
        self.assertTrue(c.differs)

    def test_no_voice_data_is_not_usable(self):
        self.assertFalse(vpart.compare("run", meta("Ava"), None).usable)
        self.assertFalse(vpart.compare("run", meta("Ava"), doc(silent=True)).usable)

    def test_two_voices_for_one_person_count_once(self):
        names = vpart.voice_names(doc(("named", "Ava", 100), ("named", "Ava", 50),
                                      ("named", "Bo", 300)))
        self.assertEqual(names, ["Bo", "Ava"])

    def test_never_heard_counts_meetings(self):
        a = vpart.compare("a", meta("Ghost"), doc(("named", "Ava", 100)))
        b = vpart.compare("b", meta("Ghost", "Ava"), doc(("named", "Ava", 100)))
        c = vpart.compare("c", meta("Ghost"), None)
        self.assertEqual(vpart.never_heard([a, b, c]), [("Ghost", 2)])


class TitleNameTests(unittest.TestCase):
    def test_whole_words_only(self):
        found = vpart.title_names("2026-01-01_1000_WeekendPlanAvaBo010126", ["Ava", "Bo", "Wee", "Plan"])
        self.assertEqual(found, ["Ava", "Bo", "Plan"])

    def test_name_with_initial(self):
        found = vpart.title_names("2026-01-01_1000_SkyB1v1010126", ["SkyB", "Sky"])
        self.assertIn("SkyB", found)

    def test_unknown_names_are_ignored(self):
        self.assertEqual(vpart.title_names("2026-01-01_1000_ZedMeeting", ["Ava"]), [])


class BuildParticipantsTests(unittest.TestCase):
    def test_heard_first_then_title_only(self):
        result = vpart.build_participants(
            "2026-01-01_1000_AvaBoCyMeeting",
            doc(("named", "Ava", 300), ("named", "Bo", 100), ("unknown", None, 60)),
            ["Ava", "Bo", "Cy"],
        )
        self.assertEqual([p["name"] for p in result], ["Ava", "Bo", "Cy"])
        self.assertEqual([p["confidence"] for p in result], ["high", "high", "low"])
        self.assertEqual(result[2]["reason"], vpart.TITLE_REASON)

    def test_mentioned_only_names_are_not_added(self):
        result = vpart.build_participants(
            "2026-01-01_1000_Standup", doc(("named", "Ava", 300)), ["Ava", "Bo"])
        self.assertEqual([p["name"] for p in result], ["Ava"])

    def test_no_voice_data_leaves_list_alone(self):
        self.assertIsNone(vpart.build_participants("2026-01-01_1000_X", None, []))
        self.assertIsNone(vpart.build_participants("2026-01-01_1000_X", doc(silent=True), []))


class ApplyAndRestoreTests(unittest.TestCase):
    def setUp(self):
        import json
        import tempfile
        from pathlib import Path
        self.json = json
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        (self.run / "meeting_metadata.json").write_text(json.dumps({
            "title": "t", "participants": [{"name": "Mentioned", "confidence": "high"}],
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        return self.json.loads((self.run / "meeting_metadata.json").read_text(encoding="utf-8"))

    def test_apply_keeps_the_old_list_and_other_fields(self):
        new = [{"name": "Ava", "confidence": "high", "reason": "r"}]
        self.assertTrue(vpart.apply_to_run(self.run, new))
        data = self.read()
        self.assertEqual(data["participants"], new)
        self.assertEqual(data[vpart.BACKUP_KEY][0]["name"], "Mentioned")
        self.assertEqual(data["title"], "t")

    def test_apply_twice_keeps_the_first_backup(self):
        vpart.apply_to_run(self.run, [{"name": "Ava"}])
        vpart.apply_to_run(self.run, [{"name": "Bo"}])
        self.assertEqual(self.read()[vpart.BACKUP_KEY][0]["name"], "Mentioned")

    def test_apply_same_list_is_a_no_op(self):
        new = [{"name": "Ava"}]
        vpart.apply_to_run(self.run, new)
        self.assertFalse(vpart.apply_to_run(self.run, new))

    def test_restore(self):
        vpart.apply_to_run(self.run, [{"name": "Ava"}])
        self.assertTrue(vpart.restore_run(self.run))
        data = self.read()
        self.assertEqual(data["participants"][0]["name"], "Mentioned")
        self.assertNotIn(vpart.BACKUP_KEY, data)
        self.assertFalse(vpart.restore_run(self.run))


if __name__ == "__main__":
    unittest.main()
