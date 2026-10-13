import unittest

from query.count_compliance import (
    build_count_retry_prompt,
    count_structured_items,
    extract_requested_count,
    needs_count_retry,
)


class QueryCountComplianceTests(unittest.TestCase):

    def test_detects_top_three(self):
        self.assertEqual(
            extract_requested_count(
                "Tell me the top three things to prepare for with Alex."
            ),
            3,
        )

    def test_detects_numeric_list_request(self):
        self.assertEqual(
            extract_requested_count(
                "Give me 5 priorities for the next meeting."
            ),
            5,
        )

    def test_ordinary_question_has_no_requested_count(self):
        self.assertIsNone(
            extract_requested_count(
                "What should I know about the Vendor Alpha renewal?"
            )
        )

    def test_counts_numbered_and_bulleted_items(self):
        response = (
            "1. First item\n"
            "2. Second item\n"
            "3. Third item\n"
        )
        self.assertEqual(
            count_structured_items(response),
            3,
        )

    def test_short_numbered_answer_triggers_retry(self):
        retry, requested, observed = needs_count_retry(
            "Tell me the top three things for Alex.",
            "1. One lonely item.",
        )

        self.assertTrue(retry)
        self.assertEqual(requested, 3)
        self.assertEqual(observed, 1)

    def test_exact_count_does_not_retry(self):
        retry, requested, observed = needs_count_retry(
            "Tell me the top three things for Alex.",
            "1. One\n2. Two\n3. Three",
        )

        self.assertFalse(retry)
        self.assertEqual(requested, 3)
        self.assertEqual(observed, 3)

    def test_supported_shortfall_does_not_force_hallucination(self):
        retry, requested, _ = needs_count_retry(
            "Give me the top three priorities.",
            "Only two supported items are available.\n1. One\n2. Two",
        )

        self.assertFalse(retry)
        self.assertEqual(requested, 3)

    def test_retry_prompt_repeats_request_and_count(self):
        prompt = build_count_retry_prompt(
            "BASE PROMPT",
            "Tell me the top three things for Alex.",
            3,
        )

        self.assertIn("exactly 3 distinct items", prompt)
        self.assertIn(
            "Tell me the top three things for Alex.",
            prompt,
        )
        self.assertIn("do not invent filler", prompt)


if __name__ == "__main__":
    unittest.main()
