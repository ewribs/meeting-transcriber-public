import math
import unittest

import voice_worker as vw


class LevelTests(unittest.TestCase):
    def test_full_scale_square_wave_is_zero_db(self):
        self.assertAlmostEqual(vw.level_db([1.0, -1.0, 1.0, -1.0]), 0.0)

    def test_half_amplitude_is_about_minus_six_db(self):
        self.assertAlmostEqual(vw.level_db([0.5, -0.5] * 4), -6.02, places=1)

    def test_empty_and_zero_are_very_quiet(self):
        self.assertEqual(vw.level_db([]), -120.0)
        self.assertEqual(vw.level_db([0.0, 0.0]), -120.0)

    def test_silence_threshold_matches_measured_recordings(self):
        self.assertFalse(vw.is_silent(-34.0))   # a normal Remote track
        self.assertTrue(vw.is_silent(-68.0))    # remote not captured


class ChunkTests(unittest.TestCase):
    def test_long_turn_is_cut_into_windows(self):
        chunks = vw.chunk_turns([(0.0, 10.0)])
        self.assertEqual(chunks, [(0.0, 4.0), (4.0, 8.0), (8.0, 10.0)])

    def test_short_tails_and_turns_are_dropped(self):
        self.assertEqual(vw.chunk_turns([(0.0, 1.5)]), [])
        self.assertEqual(vw.chunk_turns([(0.0, 5.0)]), [(0.0, 4.0)])

    def test_many_chunks_are_spread_evenly_up_to_the_cap(self):
        chunks = vw.chunk_turns([(0.0, 4000.0)], max_chunks=10)
        self.assertEqual(len(chunks), 10)
        self.assertEqual(chunks[0][0], 0.0)
        self.assertGreater(chunks[-1][0], 3000.0)


class PayloadTests(unittest.TestCase):
    def test_voice_record_rounds_and_sums(self):
        record = vw.voice_record(
            "SPEAKER_00", [(0.0, 3.0), (10.0, 12.5)], [[0.123456789, 0.5]]
        )
        self.assertEqual(record["seconds"], 5.5)
        self.assertEqual(record["fingerprints"], [[0.12346, 0.5]])
        self.assertEqual(record["turns"], [[0.0, 3.0], [10.0, 12.5]])

    def test_payload_reports_silent_remote(self):
        payload = vw.build_payload(
            duration_seconds=100.0, mean_db=-68.2, voices=[], seconds_taken=1.0
        )
        self.assertTrue(payload["remote_silent"])
        self.assertEqual(payload["version"], vw.RESULT_VERSION)
        self.assertEqual(payload["voices"], [])


if __name__ == "__main__":
    unittest.main()
