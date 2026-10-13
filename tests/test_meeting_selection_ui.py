import unittest

from meeting_selection_ui import (
    MeetingSelectionRow,
    context_status_label,
    in_context,
    selected_count_label,
    selected_runs,
    visible_runs,
)


class MeetingSelectionUiTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            MeetingSelectionRow("A", True, True),
            MeetingSelectionRow("B", False, True),
            MeetingSelectionRow("C", True, False),
            MeetingSelectionRow(None, True, True),
        ]

    def test_selected_runs_preserve_list_order(self):
        self.assertEqual(selected_runs(self.rows), ["A", "C"])

    def test_selected_count_includes_checked_rows_without_run(self):
        self.assertEqual(selected_count_label(self.rows), "Selected: 3")

    def test_visible_runs_ignore_hidden_rows(self):
        self.assertEqual(visible_runs(self.rows), ["A", "B"])

    def test_context_status_ignores_order(self):
        self.assertEqual(
            context_status_label(["A", "C"], ["C", "A"]),
            "Selected Meetings Context",
        )
        self.assertEqual(
            context_status_label(["A", "C"], ["A"]),
            "Selected Meetings Context — REBUILD REQUIRED",
        )

    def test_in_context_handles_missing_run(self):
        self.assertTrue(in_context("A", ["A", "B"]))
        self.assertFalse(in_context("C", ["A", "B"]))
        self.assertFalse(in_context(None, ["A", "B"]))


if __name__ == "__main__":
    unittest.main()
