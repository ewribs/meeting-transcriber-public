import random
import unittest

import voice_groups as vg
import voice_profiles as vp

DIM = 32


def unit(seed):
    rng = random.Random(seed)
    return vp.normalize([rng.gauss(0, 1) for _ in range(DIM)])


def near(base, seed, noise=0.1):
    rng = random.Random(seed)
    return vp.normalize([x + rng.gauss(0, noise) for x in base])


PERSON_X, PERSON_Y, PERSON_Z = unit(11), unit(12), unit(13)


def occ(run, voice_id, base, seed, seconds=120.0):
    return vg.Occurrence(run, voice_id, seconds, near(base, seed))


class ClusterTests(unittest.TestCase):
    def test_same_voice_across_meetings_forms_one_group(self):
        items = [
            occ("2026-10-01_0900_A", "V0", PERSON_X, 1),
            occ("2026-10-02_0900_B", "V1", PERSON_X, 2),
            occ("2026-10-03_0900_C", "V2", PERSON_X, 3),
            occ("2026-10-02_0900_B", "V0", PERSON_Y, 4),
        ]
        groups = vg.cluster_occurrences(items)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0].runs), 3)
        self.assertEqual(len(groups[1].runs), 1)
        self.assertFalse(groups[0].loose)

    def test_different_people_stay_apart(self):
        items = [occ("r1", "a", PERSON_X, 1), occ("r2", "b", PERSON_Y, 2),
                 occ("r3", "c", PERSON_Z, 3)]
        self.assertEqual(len(vg.cluster_occurrences(items)), 3)

    def test_groups_are_ordered_by_meetings_then_speech(self):
        items = [
            occ("r1", "a", PERSON_Y, 1, seconds=900),
            occ("r1", "b", PERSON_X, 2, seconds=60),
            occ("r2", "b", PERSON_X, 3, seconds=60),
        ]
        groups = vg.cluster_occurrences(items)
        self.assertEqual(len(groups[0].runs), 2)      # more meetings first
        self.assertEqual(groups[0].seconds, 120)

    def test_empty(self):
        self.assertEqual(vg.cluster_occurrences([]), [])

    def test_a_chain_of_loosely_related_voices_is_flagged(self):
        chain = [unit(100)]
        for k in range(1, 7):
            chain.append(vp.normalize(
                [a + 0.9 * b for a, b in zip(chain[-1], unit(100 + k))]
            ))
        items = [vg.Occurrence(f"r{i}", "v", 100, c) for i, c in enumerate(chain)]
        groups = vg.cluster_occurrences(items, link=0.65)
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0].loose)


class TitleTests(unittest.TestCase):
    def test_tokens_skip_dates_short_and_filler_words(self):
        tokens = vg.title_tokens("2026-10-05_1459_AveryQ4HuddleReviewMorganQuinn100526")
        self.assertIn("avery", tokens)
        self.assertIn("morgan", tokens)
        self.assertNotIn("huddle", tokens)
        self.assertNotIn("review", tokens)
        self.assertFalse(any(t.isdigit() for t in tokens))

    def test_hints_find_the_name_shared_by_a_groups_meetings(self):
        group = ["2026-10-01_0900_JordanSync100126", "2026-10-02_0900_PlanJordanRoadmap100226",
                 "2026-10-03_0900_JordanAndSam100326"]
        others = ["2026-10-04_0900_BudgetPlan100426", "2026-10-05_0900_SamRoadmap100526",
                  "2026-10-06_0900_PlanReview100626"]
        hints = vg.title_hints(group, group + others, known_names=set())
        self.assertEqual(hints[0], ("Jordan", 3))

    def test_known_people_are_not_suggested(self):
        group = ["2026-10-01_0900_JordanSync100126", "2026-10-02_0900_JordanPlan100226"]
        hints = vg.title_hints(group, group + ["2026-10-03_0900_Other100326"],
                               known_names={"jordan"})
        self.assertEqual(hints, [])

    def test_words_common_to_every_meeting_are_not_hints(self):
        everyone = [f"2026-10-0{i}_0900_AcmeProject10{i}26" for i in range(1, 6)]
        self.assertEqual(vg.title_hints(everyone[:3], everyone, set()), [])

    def test_no_data(self):
        self.assertEqual(vg.title_hints([], ["x"], set()), [])
        self.assertEqual(vg.title_hints(["x"], [], set()), [])


if __name__ == "__main__":
    unittest.main()
