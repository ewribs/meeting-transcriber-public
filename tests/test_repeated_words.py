import unittest

import utils


def collapse(text):
    return utils.collapse_repeated_words(text)[0]


class RepeatedWordTests(unittest.TestCase):
    def test_a_long_stutter_is_cut_to_three(self):
        self.assertEqual(collapse("Yeah, yeah, yeah, yeah, yeah, yeah, yeah, ok then"),
                         "Yeah, yeah, yeah, ok then")

    def test_ordinary_repetition_is_left_alone(self):
        for text in ("No, no, no, no way", "Yeah yeah yeah", "very very very very good",
                     "I think I think we should go", "Okay. Okay. Okay."):
            self.assertEqual(collapse(text), text)

    def test_five_in_a_row_is_cut(self):
        self.assertEqual(collapse("no no no no no way"), "no no no way")

    def test_a_repeated_phrase_is_cut_to_two(self):
        text = "Let's talk about it. Let's talk about it. Let's talk about it. Let's talk about it. Fine."
        self.assertEqual(collapse(text), "Let's talk about it. Let's talk about it. Fine.")

    def test_three_repeats_of_a_phrase_are_kept(self):
        text = "Let's talk about it. Let's talk about it. Let's talk about it. Fine."
        self.assertEqual(collapse(text), text)

    def test_counts_removed_words(self):
        self.assertEqual(utils.collapse_repeated_words("a a a a a a a b")[1], 4)

    def test_non_speech_tokens_are_not_treated_as_repeats(self):
        text = "- - - - - - done"
        self.assertEqual(collapse(text), text)

    def test_merge_step_applies_it_and_reports(self):
        entries = [utils.TranscriptEntry(0.0, 5.0, "Mic", "so so so so so so so ok")]
        result = utils.merge_adjacent_speakers(entries)
        self.assertEqual(result[0].text, "so so so ok")


if __name__ == "__main__":
    unittest.main()
