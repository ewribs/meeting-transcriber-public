import json
import os
import unittest
from unittest import mock

import closed_topic_check as ctc

TRANSCRIPT = (
    "# Meeting Transcript\n\n"
    "[00:00] **Remote**\n\nThe issue was moved to the right standard.\n\n\n"
    "[00:10] **Remote**\n\nI need to figure out if there are any others. I will come back with a confirmation.\n\n\n"
)


def memory():
    return {"topics": [
        {"topic_key": "a", "topic": "Standard Alignment", "status": "closed",
         "summary": "An issue was moved. The team confirmed no other issues are misaligned."},
        {"topic_key": "b", "topic": "Office Policy", "status": "open", "summary": "Discussed."},
    ], "commitments": [], "follow_ups": []}


def reply(*rows):
    return json.dumps({"unfinished": [
        {"topic_number": n, "remaining_work": w, "evidence": e} for n, w, e in rows]})


class CheckTests(unittest.TestCase):
    def run_check(self, ask, mem=None):
        return ctc.run_closed_topic_check("m", TRANSCRIPT, mem or memory(), ask, None)

    def test_reopens_with_verified_quote_and_fixes_summary(self):
        ask = lambda p, response_format=None: reply(
            (1, "Confirm whether any other issues are tied to the standard",
             "I need to figure out if there are any others"))
        topic = self.run_check(ask)["topics"][0]
        self.assertEqual(topic["status"], "open")
        self.assertNotIn("confirmed", topic["summary"])
        self.assertIn("An issue was moved.", topic["summary"])
        self.assertIn("Still open: Confirm whether any other issues are tied to the standard.", topic["summary"])

    def test_invented_quote_is_ignored(self):
        ask = lambda p, response_format=None: reply((1, "Confirm the other issues later", "we will meet next week"))
        self.assertEqual(self.run_check(ask)["topics"][0]["status"], "closed")

    def test_bad_topic_number_is_ignored(self):
        ask = lambda p, response_format=None: reply((5, "Confirm the other issues later", "I will come back with a confirmation"))
        self.assertEqual(self.run_check(ask)["topics"][0]["status"], "closed")

    def test_open_topics_are_never_sent(self):
        seen = []
        def ask(prompt, response_format=None):
            seen.append(prompt)
            return reply()
        self.run_check(ask)
        self.assertIn("Standard Alignment", seen[0])
        self.assertNotIn("Office Policy", seen[0])

    def test_no_closed_topics_makes_no_call(self):
        mem = memory(); mem["topics"][0]["status"] = "open"
        def ask(prompt, response_format=None):
            raise AssertionError("should not be called")
        self.assertIs(self.run_check(ask, mem), mem)

    def test_errors_are_swallowed(self):
        def ask(prompt, response_format=None):
            raise RuntimeError("boom")
        mem = memory()
        self.assertIs(self.run_check(ask, mem), mem)

    def test_off_switch(self):
        def ask(prompt, response_format=None):
            raise AssertionError("should not be called")
        mem = memory()
        with mock.patch.dict(os.environ, {"MT_CLOSED_TOPIC_CHECK": "0"}):
            self.assertIs(self.run_check(ask, mem), mem)

    def test_original_memory_is_not_mutated(self):
        ask = lambda p, response_format=None: reply(
            (1, "Confirm whether any other issues are tied to the standard", "I will come back with a confirmation"))
        mem = memory()
        self.run_check(ask, mem)
        self.assertEqual(mem["topics"][0]["status"], "closed")


if __name__ == "__main__":
    unittest.main()
