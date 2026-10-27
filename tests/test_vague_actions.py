import unittest

import ai


class VagueActionTests(unittest.TestCase):
    def check(self, action):
        return ai._commitment_action_is_self_contained(action)

    def test_standing_stances_are_not_actions(self):
        for action in ("be on top of the issue", "Stay on top of it",
                       "keep on top of the situation."):
            self.assertFalse(self.check(action), action)

    def test_something_done_in_the_meeting_is_not_a_commitment(self):
        self.assertFalse(self.check("put her note right now"))
        self.assertFalse(self.check("Send the link right now"))

    def test_real_actions_still_pass(self):
        for action in ("Send the renewal summary for signature",
                       "Stay on top of the vendor contract renewal dates",
                       "Reply to Salesforce"):
            self.assertTrue(self.check(action), action)


if __name__ == "__main__":
    unittest.main()
