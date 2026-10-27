import unittest
from unittest import mock

import config
import pipeline
import structured_cleaning as sc
from transcript_turns import Turn


def turn(number, text, speaker=None):
    return Turn(id=f"t{number:04d}", start=float(number), end=float(number) + 1,
                channel="remote", speaker=speaker or {"kind": "unidentified"},
                text_raw=text, text=text)


class ParseTests(unittest.TestCase):
    def test_reads_ids_and_paragraphs(self):
        reply = "[t0001] Hello there.\n\nSecond paragraph.\n[t0002] Yeah."
        self.assertEqual(sc.parse_reply(reply),
                         {"t0001": "Hello there.\n\nSecond paragraph.", "t0002": "Yeah."})

    def test_a_repeated_id_is_not_trusted(self):
        self.assertEqual(sc.parse_reply("[t0001] a\n[t0001] b\n[t0002] c"), {"t0002": "c"})


class AcceptTests(unittest.TestCase):
    def test_tidy_versions_pass_and_rewrites_fail(self):
        self.assertTrue(sc.acceptable("so um I will send the file tomorrow ok",
                                      "So, I will send the file tomorrow, okay."))
        self.assertFalse(sc.acceptable("so um I will send the file tomorrow ok", "Okay."))
        self.assertFalse(sc.acceptable("Yeah.", ""))
        self.assertFalse(sc.acceptable("Yeah.", "Yeah. Keep the lights on. I will meet my team."))


class CleanTests(unittest.TestCase):
    def test_a_reply_cannot_move_words_between_speakers(self):
        turns = [turn(1, "started with the existing process"), turn(2, "yeah"),
                 turn(3, "keep the lights on so i am going to meet my team")]
        # The model glues the backchannel and the next turn into the first one.
        reply = ("[t0001] Started with the existing process.\n- Yeah.\n- Keep the lights on.\n"
                 "[t0002] Yeah.\n"
                 "[t0003] Keep the lights on, so I am going to meet my team.")
        sc.clean_turns(turns, lambda prompt: reply)
        self.assertEqual(turns[0].text, "started with the existing process")   # rejected
        self.assertEqual(turns[1].text, "Yeah.")
        self.assertEqual(turns[2].text, "Keep the lights on, so I am going to meet my team.")

    def test_missing_turns_and_model_errors_keep_the_original(self):
        turns = [turn(1, "hello there everyone"), turn(2, "thanks for joining today")]
        sc.clean_turns(turns, lambda prompt: "[t0001] Hello there, everyone.")
        self.assertEqual([t.text for t in turns],
                         ["Hello there, everyone.", "thanks for joining today"])

        def broken(prompt):
            raise RuntimeError("no model")
        again = [turn(1, "hello there everyone")]
        sc.clean_turns(again, broken)
        self.assertEqual(again[0].text, "hello there everyone")

    def test_original_words_are_never_touched(self):
        turns = [turn(1, "hello there everyone")]
        sc.clean_turns(turns, lambda prompt: "[t0001] Hello there, everyone.")
        self.assertEqual(turns[0].text_raw, "hello there everyone")

    def test_groups_respect_the_word_limit(self):
        turns = [turn(n, "word " * 10) for n in range(1, 8)]
        self.assertEqual([len(g) for g in sc.groups(turns, max_words=30)], [3, 3, 1])


class PipelineHookTests(unittest.TestCase):
    def test_off_by_default(self):
        with mock.patch.object(config, "NAMED_TRANSCRIPT", False):
            self.assertIsNone(pipeline.named_cleaned_transcript("x"))

    def test_on_without_voice_data_falls_back(self):
        with mock.patch.object(config, "NAMED_TRANSCRIPT", True):
            self.assertIsNone(pipeline.named_cleaned_transcript("/nonexistent/folder"))


if __name__ == "__main__":
    unittest.main()
