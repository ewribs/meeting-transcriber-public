import unittest

import ai

DRAFT = (
    "# Meeting Summary\n\n## Decisions\n\nNone identified.\n\n## Action Items\n\nx\n\n"
    "## Risks and Concerns\n\nNone identified.\n\n## Open Questions\n\nNone identified.\n\n"
    "## Topics\n\nNone identified.\n"
)


def compose(commitments, other=None):
    memory = {"decisions": [], "commitments": commitments, "risks": [],
              "open_questions": [], "topics": []}
    if other is not None:
        memory["other_next_steps"] = other
    return ai.compose_summary_with_meeting_memory(DRAFT, memory)


class ActionSectionTests(unittest.TestCase):
    def test_a_due_date_is_shown_when_there_is_one(self):
        result = compose([{"owner": "Sam", "action": "Send the summary", "due": "Friday"}])
        self.assertIn("- Sam - Send the summary - Due: Friday", result)

    def test_without_a_due_date_the_old_wording_is_used(self):
        result = compose([{"owner": "Sam", "action": "Send the summary"}])
        self.assertIn("- Sam - Send the summary - Due date not identified", result)

    def test_other_next_steps_are_listed_under_action_items_and_labelled(self):
        result = compose([{"owner": "Sam", "action": "Send the summary"}],
                         ["Dana - Review the budget (Monday)"])
        section = result.split("## Action Items")[1].split("## Risks")[0]
        self.assertIn("**Other next steps mentioned (unconfirmed)**", section)
        self.assertIn("- Dana - Review the budget (Monday)", section)

    def test_no_other_steps_means_no_extra_block(self):
        self.assertNotIn("Other next steps", compose([{"owner": "Sam", "action": "x y z"}], []))
        self.assertNotIn("Other next steps", compose([{"owner": "Sam", "action": "x y z"}]))


if __name__ == "__main__":
    unittest.main()
