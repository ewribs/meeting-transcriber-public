import unittest

import transcript_view as tv

TRANSCRIPT = (
    "# Meeting Transcript\n\n"
    "[00:05] **Remote**\n\nHello there.\n\n"
    "[00:20] **Mic**\n\nGood to be here. I'll send that over.\n\n"
    "[01:02] **Remote**\n\nThanks.\n"
)


class TurnRecordTests(unittest.TestCase):
    def test_turns_have_time_speaker_and_exact_body(self):
        turns = tv.turn_records(TRANSCRIPT)
        self.assertEqual([t["speaker"] for t in turns], ["Remote", "Mic", "Remote"])
        self.assertEqual([t["time"] for t in turns], ["00:05", "00:20", "01:02"])
        self.assertEqual(turns[1]["body"], "Good to be here. I'll send that over.")

    def test_positions_point_at_the_body(self):
        turn = tv.turn_records(TRANSCRIPT)[0]
        self.assertEqual(TRANSCRIPT[turn["start"]:turn["end"]].strip(), "Hello there.")
        self.assertTrue(TRANSCRIPT[turn["turn_start"]:].startswith("[00:05]"))

    def test_named_speakers_are_read_like_any_other(self):
        text = "[00:05] **Alex Smith**\n\nHi.\n\n[00:09] **Unidentified**\n\nUh huh.\n"
        self.assertEqual([t["speaker"] for t in tv.turn_records(text)],
                         ["Alex Smith", "Unidentified"])

    def test_empty_and_missing_text(self):
        self.assertEqual(tv.turn_records(""), [])
        self.assertEqual(tv.turn_records(None), [])

    def test_a_turn_without_words_is_skipped(self):
        text = "[00:05] **Remote**\n\n[00:09] **Mic**\n\nHi.\n"
        self.assertEqual([t["speaker"] for t in tv.turn_records(text)], ["Mic"])


class SpeakerLookupTests(unittest.TestCase):
    def test_speaker_before_a_position(self):
        position = TRANSCRIPT.index("I'll send")
        self.assertEqual(tv.speaker_before(TRANSCRIPT, position), "Mic")

    def test_no_header_before_means_none(self):
        self.assertIsNone(tv.speaker_before("plain words", 5))
        self.assertIsNone(tv.speaker_before(TRANSCRIPT, 3))

    def test_speaker_at_prefers_the_nearest_header(self):
        self.assertEqual(tv.speaker_at(TRANSCRIPT, TRANSCRIPT.index("Thanks")), "Remote")

    def test_speaker_at_without_any_header_is_empty(self):
        self.assertEqual(tv.speaker_at("nothing here", 3), "")

    def test_header_inside_quoted_evidence_with_or_without_bracket(self):
        self.assertEqual(tv.speaker_in_header("[07:37] **Mic** I will"), "Mic")
        self.assertEqual(tv.speaker_in_header("07:37] **Remote** I will"), "Remote")
        self.assertIsNone(tv.speaker_in_header("just words"))


class DamagedHeaderTests(unittest.TestCase):
    DAMAGED = (
        "[00:05] **Remote**\n\nBefore the damage.\n\n"
        "[20:43] **\n\n\nWords left after the label was lost.\n\n"
        "[21:13] **Mic**\n\nAfter.\n"
    )

    def test_a_header_with_no_label_is_not_a_header(self):
        position = self.DAMAGED.index("Words left")
        self.assertEqual(tv.speaker_before(self.DAMAGED, position), "Remote")

    def test_the_damaged_region_does_not_invent_a_speaker(self):
        speakers = [t["speaker"] for t in tv.turn_records(self.DAMAGED)]
        self.assertEqual(speakers, ["Remote", "Mic"])

    def test_blocks_ignore_the_damaged_header(self):
        self.assertEqual([s for s, _ in tv.speaker_blocks(self.DAMAGED)], ["Remote", "Mic"])


class BlockTests(unittest.TestCase):
    def test_blocks_split_on_headers(self):
        blocks = tv.speaker_blocks(TRANSCRIPT)
        self.assertEqual([s for s, _ in blocks], ["Remote", "Mic", "Remote"])
        self.assertIn("I'll send that over.", blocks[1][1])

    def test_text_without_headers_is_one_unknown_block(self):
        self.assertEqual(tv.speaker_blocks("just some words"), [("Unknown", "just some words")])


if __name__ == "__main__":
    unittest.main()
