import json
import os
import random
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import voice_profiles as vp
import voice_service as vs

DIM = 32


def unit(seed):
    rng = random.Random(seed)
    return vp.normalize([rng.gauss(0, 1) for _ in range(DIM)])


def prints(base, count=20, seed=0):
    rng = random.Random(seed)
    return [vp.normalize([x + rng.gauss(0, 0.15) for x in base]) for _ in range(count)]


PERSON_A, PERSON_B, STRANGER = unit(1), unit(2), unit(4)


def voice_json(voice_id, base, seconds, seed=0):
    return {
        "voice_id": voice_id,
        "seconds": seconds,
        "turns": [[0.0, seconds]],
        "fingerprints": prints(base, seed=seed),
    }


def payload(*voices, silent=False):
    return {
        "version": 1,
        "models": {"diarization": "d", "embedding": "e"},
        "duration_seconds": 600.0,
        "remote_mean_db": -68.0 if silent else -30.0,
        "remote_silent": silent,
        "seconds_taken": 1.0,
        "voices": list(voices),
    }


def store_with_a_and_b():
    store = vp.VoiceStore()
    for name, base in (("Person A", PERSON_A), ("Person B", PERSON_B)):
        person = store.add_person(name)
        store.enroll(person.person_id, prints(base, seed=len(name)))
    return store


def fake_runner(result, returncode=0, stderr=""):
    def run(command, **kwargs):
        out = Path(command[command.index("--out") + 1])
        if result is not None:
            out.write_text(json.dumps(result), encoding="utf-8")
        return subprocess.CompletedProcess(command, returncode, "", stderr)
    return run


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.store = store_with_a_and_b()
        self.payload = payload(
            voice_json("V0", PERSON_A, 300),
            voice_json("V1", STRANGER, 120, seed=3),
            voice_json("V2", PERSON_B, 10, seed=4),
        )

    def test_voices_are_named_unknown_or_too_short(self):
        doc = vs.build_speakers_document(self.payload, self.store)
        status = {v["id"]: v["status"] for v in doc["voices"]}
        self.assertEqual(status, {"V0": "named", "V1": "unknown", "V2": "too_short"})
        named = doc["voices"][0]
        self.assertEqual(named["person"], "Person A")
        self.assertEqual(doc["version"], vs.SPEAKERS_VERSION)

    def test_document_has_no_fingerprints(self):
        doc = vs.build_speakers_document(self.payload, self.store)
        self.assertNotIn("fingerprints", json.dumps(doc))

    def test_created_time_can_be_set(self):
        when = datetime(2026, 1, 2, 3, 4, 5)
        doc = vs.build_speakers_document(self.payload, self.store, now=when)
        self.assertEqual(doc["created"], "2026-01-02T03:04:05")

    def test_hint_from_elimination(self):
        doc = vs.build_speakers_document(
            self.payload, self.store, ["Person A", "Person Z"]
        )
        self.assertEqual(doc["hint"], {"voice_ids": ["V1"], "name": "Person Z"})

    def test_no_hint_without_expected_names(self):
        self.assertIsNone(vs.build_speakers_document(self.payload, self.store)["hint"])

    def test_silent_remote_gives_empty_document(self):
        doc = vs.build_speakers_document(payload(silent=True), self.store)
        self.assertTrue(doc["remote_silent"])
        self.assertEqual(doc["voices"], [])

    def test_display_labels(self):
        doc = vs.build_speakers_document(self.payload, self.store)
        self.assertEqual(
            vs.display_labels(doc),
            {"V0": "Person A", "V1": "Speaker 1", "V2": "Unidentified"},
        )


class WorkerTests(unittest.TestCase):
    def run_it(self, runner):
        return vs.run_worker(Path("a.m4a"), "python", worker_path=Path("w.py"),
                             runner=runner)

    def test_result_is_returned(self):
        result = payload(voice_json("V0", PERSON_A, 100))
        self.assertEqual(self.run_it(fake_runner(result))["version"], 1)

    def test_failure_message_includes_the_end_of_the_error(self):
        with self.assertRaises(vs.VoiceServiceError) as caught:
            self.run_it(fake_runner(None, returncode=1, stderr="x\nmodel did not load"))
        self.assertIn("model did not load", str(caught.exception))

    def test_missing_result_file_is_an_error(self):
        with self.assertRaises(vs.VoiceServiceError):
            self.run_it(fake_runner(None))

    def test_wrong_version_is_an_error(self):
        bad = payload()
        bad["version"] = 99
        with self.assertRaises(vs.VoiceServiceError):
            self.run_it(fake_runner(bad))

    def test_timeout_is_reported(self):
        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 1)
        with self.assertRaises(vs.VoiceServiceError):
            self.run_it(runner)

    def test_cannot_start_is_reported(self):
        def runner(command, **kwargs):
            raise FileNotFoundError("no such python")
        with self.assertRaises(vs.VoiceServiceError):
            self.run_it(runner)


class OneOnOneTests(unittest.TestCase):
    def test_enrolls_the_main_voice(self):
        store = vp.VoiceStore()
        info = vs.enroll_one_on_one(
            store, "Person A",
            payload(voice_json("V0", PERSON_A, 900), voice_json("V1", STRANGER, 30)),
        )
        self.assertEqual(info["person_id"], "person-a")
        self.assertEqual(store.find("Person A").enrollments, 1)
        self.assertGreaterEqual(info["share"], 0.9)

    def test_refuses_silent_remote(self):
        with self.assertRaises(vs.VoiceServiceError):
            vs.enroll_one_on_one(vp.VoiceStore(), "Person A", payload(silent=True))

    def test_refuses_when_no_speech(self):
        with self.assertRaises(vs.VoiceServiceError):
            vs.enroll_one_on_one(vp.VoiceStore(), "Person A", payload())

    def test_refuses_a_call_with_several_voices(self):
        store = vp.VoiceStore()
        with self.assertRaises(vs.VoiceServiceError):
            vs.enroll_one_on_one(
                store, "Person A",
                payload(voice_json("V0", PERSON_A, 300), voice_json("V1", STRANGER, 250)),
            )
        self.assertEqual(store.people(), [])


class PendingTests(unittest.TestCase):
    def test_save_load_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp) / "pending"
            vs.save_pending("run1", payload(voice_json("V0", PERSON_A, 100)), pending)
            path = pending / "run1.json"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertIn("V0", vs.load_pending("run1", pending))
            vs.delete_pending("run1", pending)
            self.assertEqual(vs.load_pending("run1", pending), {})

    def test_missing_or_broken_pending_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp)
            self.assertEqual(vs.load_pending("none", pending), {})
            (pending / "bad.json").write_text("not json", encoding="utf-8")
            self.assertEqual(vs.load_pending("bad", pending), {})

    def test_prune_removes_only_old_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending = Path(tmp)
            old, new = pending / "old.json", pending / "new.json"
            old.write_text("{}")
            new.write_text("{}")
            os.utime(old, (1000, 1000))
            removed = vs.prune_pending(pending, max_age_days=30)
            self.assertEqual(removed, 1)
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())


class ConfirmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "run_one"
        self.run_dir.mkdir()
        self.pending = self.root / "pending"
        self.store = store_with_a_and_b()
        self.payload = payload(
            voice_json("V0", PERSON_A, 300),
            voice_json("V1", STRANGER, 120, seed=3),
            voice_json("V2", STRANGER, 60, seed=5),
        )

    def identify(self, expected=()):
        return vs.identify_recording(
            self.run_dir, Path("a.m4a"), "python", self.store, expected,
            pending_dir=self.pending, worker_path=Path("w.py"),
            runner=fake_runner(self.payload),
        )

    def test_identify_writes_speakers_and_pending(self):
        doc = self.identify()
        self.assertEqual(vs.read_speakers(self.run_dir)["voices"][0]["person"], "Person A")
        self.assertIn("V1", vs.load_pending("run_one", self.pending))
        self.assertEqual(doc["voices"][1]["status"], "unknown")

    def test_silent_remote_saves_nothing_private(self):
        self.payload = payload(silent=True)
        self.identify()
        self.assertEqual(vs.load_pending("run_one", self.pending), {})

    def test_confirm_names_the_voice_and_learns_from_it(self):
        self.identify(["Person A", "Person Z"])
        info = vs.confirm_voice(self.run_dir, "V1", "Person Z", self.store, self.pending)
        self.assertGreater(info["enrolled"], 0)
        self.assertIsNotNone(self.store.find("Person Z").centroid)
        doc = vs.read_speakers(self.run_dir)
        by_id = {v["id"]: v for v in doc["voices"]}
        self.assertEqual(by_id["V1"]["person"], "Person Z")
        self.assertEqual(by_id["V1"]["via"], "user")
        self.assertIsNone(doc["hint"])

    def test_confirmed_person_is_recognized_in_the_next_meeting(self):
        self.identify()
        vs.confirm_voice(self.run_dir, "V1", "Person Z", self.store, self.pending)
        nxt = vs.build_speakers_document(
            payload(voice_json("X", STRANGER, 200, seed=9)), self.store
        )
        self.assertEqual(nxt["voices"][0]["person"], "Person Z")

    def test_confirm_also_names_matching_fragments(self):
        self.identify()
        vs.confirm_voice(self.run_dir, "V1", "Person Z", self.store, self.pending)
        doc = vs.read_speakers(self.run_dir)
        by_id = {v["id"]: v for v in doc["voices"]}
        self.assertEqual(by_id["V2"]["person"], "Person Z")

    def test_confirm_without_saved_fingerprints_still_names(self):
        self.identify()
        vs.delete_pending("run_one", self.pending)
        info = vs.confirm_voice(self.run_dir, "V1", "Person Z", self.store, self.pending)
        self.assertEqual(info["enrolled"], 0)
        self.assertEqual(vs.read_speakers(self.run_dir)["voices"][1]["person"], "Person Z")

    def test_confirm_errors(self):
        with self.assertRaises(vs.VoiceServiceError):
            vs.confirm_voice(self.run_dir, "V1", "Person Z", self.store, self.pending)
        self.identify()
        with self.assertRaises(vs.VoiceServiceError):
            vs.confirm_voice(self.run_dir, "nope", "Person Z", self.store, self.pending)


class KeepConfirmationsTests(unittest.TestCase):
    def setUp(self):
        self.store = store_with_a_and_b()
        self.payload = payload(
            voice_json("V0", PERSON_A, 300),
            voice_json("V1", STRANGER, 120, seed=3),
        )

    def confirmed_document(self):
        doc = vs.build_speakers_document(self.payload, self.store, ["Person A", "Person Z"])
        voice = doc["voices"][1]
        voice.update({"status": "named", "via": "user",
                      "person_id": "person-z", "person": "Person Z"})
        doc["hint"] = None
        return doc

    def test_user_names_survive_a_fresh_analysis(self):
        old = self.confirmed_document()
        fresh = vs.build_speakers_document(self.payload, self.store, ["Person A", "Person Z"])
        self.assertEqual(fresh["voices"][1]["status"], "unknown")
        merged = vs.keep_confirmations(old, fresh)
        self.assertEqual(merged["voices"][1]["person"], "Person Z")
        self.assertEqual(merged["voices"][1]["via"], "user")
        self.assertIsNone(merged["hint"])

    def test_automatic_names_are_recomputed_not_kept(self):
        old = vs.build_speakers_document(self.payload, self.store)
        fresh = vs.build_speakers_document(self.payload, vp.VoiceStore())
        merged = vs.keep_confirmations(old, fresh)
        self.assertEqual(merged["voices"][0]["status"], "unknown")

    def test_hint_stays_when_the_confirmed_voice_is_a_different_one(self):
        old = self.confirmed_document()
        fresh = vs.build_speakers_document(self.payload, self.store, ["Person A", "Person Z"])
        fresh["voices"].append(dict(fresh["voices"][1], id="V9"))
        fresh["hint"] = {"voice_ids": ["V9"], "name": "Person Y"}
        merged = vs.keep_confirmations(old, fresh)
        self.assertIsNotNone(merged["hint"])

    def test_no_old_document(self):
        fresh = vs.build_speakers_document(self.payload, self.store)
        self.assertIs(vs.keep_confirmations(None, fresh), fresh)

    def test_voices_that_disappeared_are_ignored(self):
        old = self.confirmed_document()
        old["voices"][1]["id"] = "GONE"
        fresh = vs.build_speakers_document(self.payload, self.store)
        merged = vs.keep_confirmations(old, fresh)
        self.assertEqual(merged["voices"][1]["status"], "unknown")


class SpeakersFileTests(unittest.TestCase):
    def test_missing_and_broken_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.assertIsNone(vs.read_speakers(run))
            (run / vs.SPEAKERS_FILE).write_text("not json", encoding="utf-8")
            with self.assertRaises(vs.VoiceServiceError):
                vs.read_speakers(run)
            (run / vs.SPEAKERS_FILE).write_text(json.dumps({"version": 99}), encoding="utf-8")
            with self.assertRaises(vs.VoiceServiceError):
                vs.read_speakers(run)


if __name__ == "__main__":
    unittest.main()
