import unittest

from session_criteria_ui import (
    ANY_PERSON_LABEL,
    HISTORY_OPTIONS,
    available_people,
    build_create_criteria,
    build_edit_criteria,
    criteria_present,
    edit_history_state,
)


class SessionCriteriaUiTests(unittest.TestCase):
    def test_available_people_dedupes_and_sorts(self):
        meetings = [
            {"participants": ["Alex", " Jordan "]},
            {"participants": ["alex", "", "Taylor"]},
        ]
        self.assertEqual(
            available_people(meetings),
            ["Alex", "alex", "Jordan", "Taylor"],
        )

    def test_current_person_is_kept_when_not_in_catalog(self):
        self.assertEqual(
            available_people([], current_person="Alex"),
            ["Alex"],
        )

    def test_create_person_only_with_history_window(self):
        criteria = build_create_criteria(
            person_text="Alex",
            title_text="",
            topic_text="",
            history_label="Last 30 days",
        )
        self.assertEqual(criteria["person"], "Alex")
        self.assertIsNone(criteria["title"])
        self.assertIsNone(criteria["topic"])
        self.assertEqual(criteria["history_days"], 30)
        self.assertTrue(criteria_present(criteria))

    def test_any_person_all_history_has_no_criteria(self):
        criteria = build_create_criteria(
            person_text=ANY_PERSON_LABEL,
            title_text="",
            topic_text="",
            history_label="All history",
        )
        self.assertFalse(criteria_present(criteria))

    def test_edit_preserves_saved_custom_range(self):
        selection = {
            "history_days": None,
            "start_date": "2026-08-01",
            "end_date": "2026-09-01",
        }
        options, current, custom = edit_history_state(selection)
        self.assertEqual(options[:4], list(HISTORY_OPTIONS))
        self.assertEqual(current, custom)

        criteria = build_edit_criteria(
            person_text="Alex",
            title_text="",
            topic_text="",
            selected_history_label=current,
            custom_range_label=custom,
            saved_start_date="2026-08-01",
            saved_end_date="2026-09-01",
        )
        self.assertIsNone(criteria["history_days"])
        self.assertEqual(criteria["start_date"], "2026-08-01")
        self.assertEqual(criteria["end_date"], "2026-09-01")

    def test_edit_switching_to_rolling_window_drops_saved_range(self):
        criteria = build_edit_criteria(
            person_text="Alex",
            title_text="1v1",
            topic_text="",
            selected_history_label="Last 90 days",
            custom_range_label="Keep saved date range: 2026-08-01 to 2026-09-01",
            saved_start_date="2026-08-01",
            saved_end_date="2026-09-01",
        )
        self.assertEqual(criteria["history_days"], 90)
        self.assertIsNone(criteria["start_date"])
        self.assertIsNone(criteria["end_date"])


if __name__ == "__main__":
    unittest.main()
