import json
import math
import random
import tempfile
import unittest
from pathlib import Path

import voice_profiles as vp

DIM = 32


def unit_vector(seed: int) -> list[float]:
    rng = random.Random(seed)
    return vp.normalize([rng.gauss(0, 1) for _ in range(DIM)])


def samples(base, count=20, noise=0.15, seed=0):
    """Fingerprints that sound like `base`, with some natural variation."""
    rng = random.Random(seed)
    return [
        vp.normalize([x + rng.gauss(0, noise) for x in base])
        for _ in range(count)
    ]


PERSON_A = unit_vector(1)
PERSON_B = unit_vector(2)
PERSON_C = unit_vector(3)
STRANGER = unit_vector(4)


def store_with(*people):
    store = vp.VoiceStore()
    for name, base in people:
        person = store.add_person(name)
        store.enroll(person.person_id, samples(base, seed=len(name)))
    return store


def voice(voice_id, base, seconds=120.0, seed=7):
    return vp.VoiceInput(voice_id, seconds, samples(base, count=10, seed=seed))


class VectorTests(unittest.TestCase):
    def test_normalize_gives_unit_length(self):
        v = vp.normalize([3.0, 4.0])
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in v)), 1.0)

    def test_normalize_rejects_bad_input(self):
        for bad in ([], [0.0, 0.0], [1.0, float("nan")], [float("inf"), 1.0]):
            with self.assertRaises(ValueError):
                vp.normalize(bad)

    def test_dot_requires_same_length(self):
        with self.assertRaises(ValueError):
            vp.dot([1.0, 0.0], [1.0])

    def test_centroid_is_close_to_its_samples(self):
        c = vp.centroid(samples(PERSON_A))
        self.assertGreater(vp.dot(c, PERSON_A), 0.95)

    def test_clean_centroid_ignores_stray_voices(self):
        good = samples(PERSON_A, count=30)
        strays = samples(STRANGER, count=2)
        plain = vp.centroid(good + strays)
        cleaned = vp.clean_centroid(good + strays)
        self.assertGreaterEqual(vp.dot(cleaned, PERSON_A), vp.dot(plain, PERSON_A))
        self.assertGreater(vp.dot(cleaned, PERSON_A), 0.95)


class StoreTests(unittest.TestCase):
    def test_add_find_and_duplicates(self):
        store = vp.VoiceStore()
        a = store.add_person("Person A")
        self.assertIs(store.find("person a"), a)
        self.assertIs(store.find(a.person_id), a)
        with self.assertRaises(ValueError):
            store.add_person("PERSON A")
        with self.assertRaises(ValueError):
            store.add_person("   ")
        self.assertIs(store.ensure_person("Person A"), a)

    def test_ids_stay_unique_for_similar_names(self):
        store = vp.VoiceStore()
        first = store.add_person("Person-A")
        second = store.add_person("Person A!")
        self.assertNotEqual(first.person_id, second.person_id)

    def test_enroll_needs_enough_fingerprints(self):
        store = vp.VoiceStore()
        person = store.add_person("Person A")
        with self.assertRaises(ValueError):
            store.enroll(person.person_id, samples(PERSON_A, count=2))

    def test_enroll_trims_to_the_limit(self):
        store = vp.VoiceStore(max_fingerprints=10)
        person = store.add_person("Person A")
        store.enroll(person.person_id, samples(PERSON_A, count=25))
        self.assertEqual(len(person.fingerprints), 10)
        self.assertEqual(person.enrollments, 1)
        self.assertIsNotNone(person.centroid)

    def test_enroll_rejects_different_length(self):
        store = vp.VoiceStore()
        person = store.add_person("Person A")
        store.enroll(person.person_id, samples(PERSON_A))
        with self.assertRaises(ValueError):
            store.enroll(person.person_id, [[1.0, 0.0]] * 5)

    def test_rename_keeps_old_name_as_alias(self):
        store = vp.VoiceStore()
        person = store.add_person("Person A")
        store.rename_person(person.person_id, "Person Alpha")
        self.assertEqual(store.find("person a"), person)
        self.assertEqual(person.name, "Person Alpha")

    def test_remove_person(self):
        store = store_with(("Person A", PERSON_A))
        store.remove_person("person-a")
        self.assertEqual(store.people(), [])
        with self.assertRaises(KeyError):
            store.remove_person("person-a")

    def test_save_and_load_round_trip(self):
        store = store_with(("Person A", PERSON_A), ("Person B", PERSON_B))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voices" / "profiles.json"
            store.save(path)
            loaded = vp.VoiceStore.load(path)
            self.assertEqual(
                [p.name for p in loaded.people()], ["Person A", "Person B"]
            )
            sims = vp.dot(
                loaded.find("Person A").centroid, store.find("Person A").centroid
            )
            self.assertGreater(sims, 0.999)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            leftovers = [p.name for p in path.parent.iterdir()]
            self.assertEqual(leftovers, ["profiles.json"])

    def test_missing_file_gives_empty_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(vp.VoiceStore.load(Path(tmp) / "none.json").people(), [])

    def test_bad_files_raise_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            for text in ("not json", json.dumps({"version": 99, "people": []}),
                         json.dumps({"version": 1})):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(vp.VoiceStoreError):
                    vp.VoiceStore.load(path)


class IdentifyTests(unittest.TestCase):
    def setUp(self):
        self.store = store_with(
            ("Person A", PERSON_A), ("Person B", PERSON_B)
        )

    def by_id(self, results):
        return {r.voice_id: r for r in results}

    def test_known_voice_is_named(self):
        results = self.by_id(vp.identify_voices([voice("v1", PERSON_A)], self.store))
        self.assertEqual(results["v1"].status, "named")
        self.assertEqual(results["v1"].person_id, "person-a")
        self.assertEqual(results["v1"].via, "match")

    def test_stranger_stays_unknown(self):
        results = self.by_id(vp.identify_voices([voice("v1", STRANGER)], self.store))
        self.assertEqual(results["v1"].status, "unknown")
        self.assertIsNone(results["v1"].person_id)

    def test_short_voice_is_not_judged(self):
        results = self.by_id(
            vp.identify_voices([voice("v1", PERSON_A, seconds=10)], self.store)
        )
        self.assertEqual(results["v1"].status, "too_short")

    def test_near_tie_is_not_named(self):
        blend = vp.normalize([a + b for a, b in zip(PERSON_A, PERSON_B)])
        results = self.by_id(vp.identify_voices([voice("v1", blend)], self.store))
        self.assertEqual(results["v1"].status, "unknown")
        self.assertLess(results["v1"].gap, vp.NAME_GAP)

    def test_no_profiles_means_unknown(self):
        results = self.by_id(
            vp.identify_voices([voice("v1", PERSON_A)], vp.VoiceStore())
        )
        self.assertEqual(results["v1"].status, "unknown")

    def test_two_voices_of_one_person_are_both_named(self):
        voices = [voice("v1", PERSON_A, seed=1), voice("v2", PERSON_A, seed=2)]
        results = self.by_id(vp.identify_voices(voices, self.store))
        self.assertEqual(results["v1"].person_id, "person-a")
        self.assertEqual(results["v2"].person_id, "person-a")
        self.assertIn("v2", results["v1"].same_as)

    def test_weak_fragment_takes_the_name_of_its_matching_voice(self):
        # A fragment that is close to Person A, but not close enough to be
        # named on its own.
        overlap = vp.dot(PERSON_C, PERSON_A)
        orthogonal = vp.normalize(
            [c - overlap * a for c, a in zip(PERSON_C, PERSON_A)]
        )
        closeness = 0.72
        fragment_base = vp.normalize(
            [closeness * a + math.sqrt(1 - closeness ** 2) * o
             for a, o in zip(PERSON_A, orthogonal)]
        )
        fragment = voice("frag", fragment_base, seed=3)
        solid = voice("solid", PERSON_A, seed=4)

        alone = vp.identify_voices([fragment], self.store)[0]
        self.assertEqual(alone.status, "unknown")

        results = self.by_id(vp.identify_voices([solid, fragment], self.store))
        self.assertEqual(results["solid"].via, "match")
        self.assertEqual(results["frag"].status, "named")
        self.assertEqual(results["frag"].person_id, "person-a")
        self.assertEqual(results["frag"].via, "grouped")

    def test_fragment_near_two_different_people_is_not_grouped(self):
        voices = [voice("a", PERSON_A), voice("b", PERSON_B)]
        blend = vp.normalize([a + b for a, b in zip(PERSON_A, PERSON_B)])
        voices.append(voice("mix", blend, seed=9))
        results = self.by_id(vp.identify_voices(voices, self.store))
        self.assertEqual(results["mix"].status, "unknown")

    def test_voice_between_two_named_people_is_not_grouped(self):
        voices = [voice("a", PERSON_A), voice("b", PERSON_B)]
        results = self.by_id(vp.identify_voices(voices, self.store))
        self.assertEqual(results["a"].person_id, "person-a")
        self.assertEqual(results["b"].person_id, "person-b")
        self.assertEqual(results["a"].same_as, [])

    def test_different_strangers_are_not_linked(self):
        voices = [voice("x", STRANGER), voice("y", PERSON_C)]
        results = self.by_id(vp.identify_voices(voices, self.store))
        self.assertEqual(results["x"].same_as, [])
        self.assertEqual(results["y"].same_as, [])

    def test_results_keep_input_order(self):
        voices = [voice("z", PERSON_A), voice("a", PERSON_B), voice("m", STRANGER)]
        results = vp.identify_voices(voices, self.store)
        self.assertEqual([r.voice_id for r in results], ["z", "a", "m"])


class EliminationTests(unittest.TestCase):
    def setUp(self):
        self.store = store_with(("Person A", PERSON_A), ("Person B", PERSON_B))

    def hint(self, voices, expected):
        results = vp.identify_voices(voices, self.store)
        return vp.suggest_by_elimination(results, expected, self.store)

    def test_one_left_over_voice_and_one_left_over_name(self):
        hint = self.hint(
            [voice("v1", PERSON_A), voice("v2", PERSON_B), voice("v3", STRANGER)],
            ["Person A", "Person B", "Person Z"],
        )
        self.assertEqual(hint.name, "Person Z")
        self.assertEqual(hint.voice_ids, ("v3",))

    def test_names_match_without_regard_to_case_or_spaces(self):
        hint = self.hint(
            [voice("v1", PERSON_A), voice("v3", STRANGER)],
            ["  person a ", "PERSON Z"],
        )
        self.assertEqual(hint.name, "PERSON Z")

    def test_two_left_over_names_give_no_hint(self):
        hint = self.hint(
            [voice("v1", PERSON_A), voice("v3", STRANGER)],
            ["Person A", "Person Y", "Person Z"],
        )
        self.assertIsNone(hint)

    def test_two_left_over_people_give_no_hint(self):
        hint = self.hint(
            [voice("v1", PERSON_A), voice("v3", STRANGER), voice("v4", PERSON_C)],
            ["Person A", "Person Z"],
        )
        self.assertIsNone(hint)

    def test_fragments_of_one_person_count_as_one(self):
        hint = self.hint(
            [voice("v1", PERSON_A), voice("s1", STRANGER, seed=1),
             voice("s2", STRANGER, seed=2)],
            ["Person A", "Person Z"],
        )
        self.assertEqual(hint.name, "Person Z")
        self.assertEqual(set(hint.voice_ids), {"s1", "s2"})

    def test_short_voices_are_ignored(self):
        hint = self.hint(
            [voice("v1", PERSON_A), voice("v3", STRANGER),
             voice("tiny", PERSON_C, seconds=5)],
            ["Person A", "Person Z"],
        )
        self.assertEqual(hint.voice_ids, ("v3",))

    def test_expected_person_who_did_not_match_is_left_over(self):
        # Person B has a profile but does not appear to speak.
        hint = self.hint(
            [voice("v1", PERSON_A), voice("v3", STRANGER)],
            ["Person A", "Person B"],
        )
        self.assertEqual(hint.name, "Person B")

    def test_nobody_left_over_gives_no_hint(self):
        hint = self.hint(
            [voice("v1", PERSON_A), voice("v2", PERSON_B)],
            ["Person A", "Person B"],
        )
        self.assertIsNone(hint)


class RemoveMatchingTests(unittest.TestCase):
    def test_removes_only_the_fingerprints_that_were_learned(self):
        store = vp.VoiceStore()
        person = store.add_person("Person A")
        mistaken = samples(PERSON_B, count=10, seed=7)
        store.enroll(person.person_id, samples(PERSON_A, count=20, seed=1))
        store.enroll(person.person_id, mistaken)
        self.assertEqual(person.enrollments, 2)
        removed = store.remove_matching(person.person_id, mistaken)
        self.assertEqual(removed, 10)
        self.assertEqual(len(person.fingerprints), 20)
        self.assertEqual(person.enrollments, 1)
        self.assertGreater(vp.dot(person.centroid, PERSON_A), 0.9)

    def test_nothing_matching_changes_nothing(self):
        store = vp.VoiceStore()
        person = store.add_person("Person A")
        store.enroll(person.person_id, samples(PERSON_A, count=10, seed=1))
        self.assertEqual(
            store.remove_matching(person.person_id, samples(PERSON_B, count=5, seed=3)), 0)
        self.assertEqual(person.enrollments, 1)

    def test_removing_everything_leaves_an_empty_profile(self):
        store = vp.VoiceStore()
        person = store.add_person("Person A")
        prints = samples(PERSON_A, count=5, seed=1)
        store.enroll(person.person_id, prints)
        store.remove_matching(person.person_id, prints)
        self.assertEqual(person.fingerprints, [])
        self.assertIsNone(person.centroid)


if __name__ == "__main__":
    unittest.main()
