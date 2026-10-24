import array
import math
import random
import subprocess
import unittest
from pathlib import Path

import voice_noise as vn

RATE = vn.SAMPLE_RATE


def white_noise(seconds, amplitude=2000, seed=1):
    rng = random.Random(seed)
    return array.array("h", (int(rng.gauss(0, amplitude)) for _ in range(int(seconds * RATE))))


def speech_like(seconds, seed=2):
    """A voiced tone with harmonics, loud and soft syllables and pauses."""
    rng = random.Random(seed)
    out = array.array("h")
    for i in range(int(seconds * RATE)):
        t = i / RATE
        syllable = max(0.0, math.sin(2 * math.pi * 3.5 * t)) ** 2     # on/off about 3-4 times a second
        gap = 0.0 if (t % 1.7) > 1.3 else 1.0                          # a pause every so often
        f0 = 120 + 15 * math.sin(2 * math.pi * 0.7 * t)
        tone = sum(math.sin(2 * math.pi * f0 * h * t) / h for h in range(1, 15))
        out.append(int(5000 * syllable * gap * tone + rng.gauss(0, 20)))
    return out


class MeasureTests(unittest.TestCase):
    def test_white_noise_is_flat_and_steady(self):
        metrics = vn.measure(white_noise(20), [[0, 20]])
        self.assertGreater(metrics["flatness"], 0.5)
        self.assertLess(metrics["dynamics_db"], 6)
        self.assertEqual(vn.verdict(metrics), "likely static")

    def test_speech_like_audio_is_peaked_and_varies(self):
        metrics = vn.measure(speech_like(20), [[0, 20]])
        self.assertLess(metrics["flatness"], 0.2)
        self.assertGreater(metrics["dynamics_db"], 15)
        self.assertEqual(vn.verdict(metrics), "speech-like")

    def test_near_silence_is_silent(self):
        quiet = array.array("h", [0] * (RATE * 5))
        metrics = vn.measure(quiet, [[0, 5]])
        self.assertEqual(vn.verdict(metrics), "silent")
        faint = white_noise(5, amplitude=2)
        self.assertEqual(vn.verdict(vn.measure(faint, [[0, 5]])), "silent")

    def test_only_the_turns_are_measured(self):
        mixed = speech_like(10) + white_noise(10)
        speech = vn.measure(mixed, [[0, 10]])
        hiss = vn.measure(mixed, [[10, 20]])
        self.assertEqual(vn.verdict(speech), "speech-like")
        self.assertEqual(vn.verdict(hiss), "likely static")

    def test_no_turns_or_turns_past_the_end(self):
        self.assertEqual(vn.verdict(vn.measure(white_noise(2), [])), "silent")
        self.assertEqual(vn.verdict(vn.measure(white_noise(2), [[50, 60]])), "silent")


class CheckMeetingTests(unittest.TestCase):
    def test_every_voice_gets_a_row_and_nothing_is_written(self):
        samples = speech_like(8) + white_noise(8)
        raw = samples.tobytes()

        def fake_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, raw, b"")

        document = {"voices": [
            {"id": "SPEAKER_00", "seconds": 8, "status": "named", "person": "Alex",
             "turns": [[0, 8]]},
            {"id": "SPEAKER_01", "seconds": 8, "status": "unknown",
             "turns": [[8, 16]]},
        ]}
        rows = vn.check_meeting(Path("remote.wav"), document, fake_runner)
        self.assertEqual([r["verdict"] for r in rows], ["speech-like", "likely static"])
        self.assertEqual(rows[0]["person"], "Alex")


class TagDocumentTests(unittest.TestCase):
    def setUp(self):
        samples = speech_like(8) + white_noise(8) + speech_like(8, seed=5)
        raw = samples.tobytes()
        self.runner = lambda command, **kw: subprocess.CompletedProcess(command, 0, raw, b"")
        self.document = {"voices": [
            {"id": "A", "seconds": 8, "status": "named", "person": "Alex", "turns": [[8, 16]]},
            {"id": "B", "seconds": 8, "status": "unknown", "turns": [[8, 16]]},
            {"id": "C", "seconds": 8, "status": "unknown", "turns": [[16, 24]]},
        ]}

    def test_static_is_marked_speech_is_not_and_named_voices_are_never_measured(self):
        marked = vn.tag_document(Path("x.wav"), self.document, self.runner)
        by_id = {v["id"]: v for v in self.document["voices"]}
        self.assertEqual(marked, 1)
        self.assertNotIn("noise", by_id["A"])      # named, even over noise
        self.assertEqual(by_id["B"]["noise"], "static")
        self.assertNotIn("noise", by_id["C"])
        self.assertTrue(self.document["noise_checked"])

    def test_a_mark_is_removed_when_the_voice_now_sounds_like_speech(self):
        self.document["voices"][2]["noise"] = "static"
        vn.tag_document(Path("x.wav"), self.document, self.runner)
        self.assertNotIn("noise", self.document["voices"][2])

    def test_nothing_unnamed_means_no_audio_is_read(self):
        def boom(*a, **k):
            raise AssertionError("audio should not be read")
        doc = {"voices": [{"id": "A", "seconds": 8, "status": "named",
                           "person": "Alex", "turns": [[0, 8]]}]}
        self.assertEqual(vn.tag_document(Path("x.wav"), doc, boom), 0)
        self.assertTrue(doc["noise_checked"])


if __name__ == "__main__":
    unittest.main()
