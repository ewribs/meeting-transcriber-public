import unittest

import ai


def clean(action, owner="Ribs"):
    memory = {"commitments": [{"owner": owner, "action": action, "status": "open"}],
              "decisions": [], "risks": [], "open_questions": [], "follow_ups": []}
    return ai._high_performance_memory_quality_cleanup(memory)["commitments"]


class BareActionFilterTests(unittest.TestCase):
    def test_drops_bare_take_it_for_named_owner(self):
        self.assertEqual(clean("Take it"), [])
        self.assertEqual(clean("Take the issue"), [])
        self.assertEqual(clean("Handle this."), [])

    def test_keeps_specific_actions(self):
        self.assertEqual(len(clean("Take the vendor call with Dana")), 1)
        self.assertEqual(len(clean("Send the contract to Dana")), 1)
        self.assertEqual(len(clean("Take the lead on the renewal")), 1)


if __name__ == "__main__":
    unittest.main()
