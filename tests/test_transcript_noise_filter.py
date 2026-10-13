import unittest

from utils import (
    LAST_NOISE_REPORT,
    TranscriptEntry,
    has_speech_characters,
    is_repetition_loop,
    merge_adjacent_speakers,
    remove_silence_entries,
    repetition_ratio,
)


def entry(start, speaker, text, length=2.0):
    return TranscriptEntry(
        start=float(start),
        end=float(start) + length,
        speaker=speaker,
        text=text,
    )


LOOP_TEXT = (
    "And then we're going to give it a name. "
    "And then we're going to give it a name. "
    "And then we're going to give it a name. "
    "And then we're going to give it a name. "
    "And then we're going to give it a name."
)

NORMAL_TEXT = (
    "We reviewed the vendor proposal this morning and the pricing looks "
    "reasonable, but the contract term is longer than we expected. "
    "Maria will confirm the renewal date with legal before Friday."
)


class SpeechCharacterTests(unittest.TestCase):
    def test_punctuation_only_is_not_speech(self):
        for text in (".", "...", "-", " . ", "?!"):
            self.assertFalse(has_speech_characters(text), text)

    def test_words_and_numbers_are_speech(self):
        for text in ("Okay.", "7", "Yes, sure."):
            self.assertTrue(has_speech_characters(text), text)


class RepetitionTests(unittest.TestCase):
    def test_loop_is_detected(self):
        self.assertTrue(is_repetition_loop(LOOP_TEXT))
        self.assertLess(repetition_ratio(LOOP_TEXT), 0.60)

    def test_normal_speech_is_kept(self):
        self.assertFalse(is_repetition_loop(NORMAL_TEXT))

    def test_short_text_is_never_a_loop(self):
        self.assertFalse(is_repetition_loop("Yeah yeah yeah yeah yeah."))
        self.assertEqual(repetition_ratio("ok"), 1.0)


class RemoveSilenceEntriesTests(unittest.TestCase):
    def test_removes_punctuation_only_and_silence_markers(self):
        entries = [
            entry(0, "Remote", "Hello everyone."),
            entry(5, "Mic", "."),
            entry(8, "Mic", "[Silence]"),
            entry(10, "Mic", "..."),
            entry(12, "Remote", "Let's begin."),
        ]

        kept = remove_silence_entries(entries)

        self.assertEqual(
            [item.text for item in kept],
            ["Hello everyone.", "Let's begin."],
        )
        self.assertEqual(LAST_NOISE_REPORT["empty_entries"], 2)

    def test_keeps_real_short_replies(self):
        entries = [entry(0, "Mic", "Okay."), entry(3, "Mic", "Yes.")]
        self.assertEqual(len(remove_silence_entries(entries)), 2)


class MergeAdjacentSpeakersTests(unittest.TestCase):
    def test_removing_noise_lets_remote_speech_join_up(self):
        entries = [
            entry(0, "Remote", "First part of the thought,"),
            entry(3, "Mic", "."),
            entry(5, "Remote", "and the second part."),
        ]

        final = merge_adjacent_speakers(remove_silence_entries(entries))

        self.assertEqual(len(final), 1)
        self.assertEqual(final[0].speaker, "Remote")
        self.assertEqual(
            final[0].text,
            "First part of the thought, and the second part.",
        )

    def test_drops_repetition_loop_and_reports_it(self):
        entries = [
            entry(0, "Remote", NORMAL_TEXT),
            entry(30, "Mic", LOOP_TEXT),
            entry(60, "Remote", "Thanks, that covers it."),
        ]

        final = merge_adjacent_speakers(remove_silence_entries(entries))

        self.assertEqual([item.speaker for item in final], ["Remote", "Remote"])
        self.assertEqual(LAST_NOISE_REPORT["repetition_loops"], 1)

    def test_clean_transcript_is_unchanged(self):
        entries = [
            entry(0, "Remote", "Good morning."),
            entry(30, "Mic", "Morning, thanks for joining."),
        ]

        final = merge_adjacent_speakers(remove_silence_entries(entries))

        self.assertEqual(len(final), 2)
        self.assertEqual(LAST_NOISE_REPORT["empty_entries"], 0)
        self.assertEqual(LAST_NOISE_REPORT["repetition_loops"], 0)


if __name__ == "__main__":
    unittest.main()
