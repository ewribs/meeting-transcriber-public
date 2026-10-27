import copy
import json
import re
import unittest

import config
import memory_reconciliation as mr
import next_steps_pass as nsp
import transcript_view as tv

SELF = str(config.SELF_NAME)
OTHER = "Pat Lee"

LEDGER = [{
    "event_type": "commitment", "owner": "Sam", "disposition": "candidate",
    "lifecycle": "planned", "subject": "Talk to Dana this week",
    "evidence": "send an email message to Dana",
}]


def empty_memory():
    return {"commitments": [], "follow_ups": [], "open_questions": [],
            "decisions": [], "risks": []}


def single_turn_transcript(speaker, other="Remote"):
    return (
        f"[00:05] **{other}**\n\nWe should reach out to Dana about the budget.\n\n"
        f"[00:20] **{speaker}**\n\nI'll try and talk to her this week for sure\n\n"
        f"[00:40] **{other}**\n\nGreat.\n"
    )


def split_turn_transcript(speaker, other="Remote"):
    return (
        f"[00:05] **{other}**\n\nWe should reach out to Dana about the budget.\n\n"
        f"[00:20] **{speaker}**\n\nYes I'll try\n\n"
        f"[00:24] **{other}**\n\nUh huh.\n\n"
        f"[00:27] **{speaker}**\n\nand talk to her this week for sure\n\n"
        f"[00:40] **{other}**\n\nGreat.\n"
    )


class WhoIsTheUserTests(unittest.TestCase):
    def test_mic_and_the_users_own_name_are_the_user(self):
        self.assertTrue(tv.is_self_speaker("Mic"))
        self.assertTrue(tv.is_self_speaker(" mic "))
        self.assertTrue(tv.is_self_speaker(SELF))
        self.assertTrue(tv.is_self_speaker(SELF.upper()))

    def test_everyone_else_is_not(self):
        for label in ("Remote", OTHER, "Unidentified", "Unknown", "", None):
            self.assertFalse(tv.is_self_speaker(label), label)

    def test_marker_pattern_matches_only_the_user(self):
        pattern = re.compile(tv.self_marker_pattern(), re.I)
        self.assertTrue(pattern.search("[00:01] **Mic** hi"))
        self.assertTrue(pattern.search(f"[00:01] **{SELF}** hi"))
        self.assertFalse(pattern.search("[00:01] **Remote** hi"))
        self.assertFalse(pattern.search(f"[00:01] **{OTHER}** hi"))


class MissedWorkTests(unittest.TestCase):
    def run_it(self, transcript):
        return mr.recover_supported_missed_work(
            {"commitments": [], "follow_ups": []}, copy.deepcopy(LEDGER), transcript)

    def test_users_own_promise_is_recovered_under_mic(self):
        self.assertEqual(len(self.run_it(single_turn_transcript("Mic"))["commitments"]), 1)

    def test_users_own_promise_is_recovered_under_their_name(self):
        self.assertEqual(len(self.run_it(single_turn_transcript(SELF, OTHER))["commitments"]), 1)

    def test_someone_elses_promise_is_not_the_users(self):
        self.assertEqual(self.run_it(single_turn_transcript(OTHER, "Remote"))["commitments"], [])
        self.assertEqual(self.run_it(single_turn_transcript("Remote", "Mic"))["commitments"], [])


class AuditedOmissionTests(unittest.TestCase):
    def run_it(self, transcript):
        result, _ = mr.recover_audited_omissions(
            empty_memory(), copy.deepcopy(LEDGER), transcript)
        return result["commitments"]

    def test_split_promise_under_mic_and_under_the_users_name_agree(self):
        legacy = self.run_it(split_turn_transcript("Mic", "Remote"))
        named = self.run_it(split_turn_transcript(SELF, OTHER))
        self.assertEqual(len(legacy), 1)
        self.assertEqual(legacy, named)

    def test_split_promise_by_someone_else_is_not_recovered(self):
        self.assertEqual(self.run_it(split_turn_transcript(OTHER, "Mic")), [])


class NarrowEvidenceTests(unittest.TestCase):
    def memory(self, owner, speaker):
        evidence = (f"[00:01:05] **{speaker}** I'll try [00:01:10] **Remote** uh huh "
                    f"[00:01:12] **{speaker}** and talk to her this week for sure")
        return {"commitments": [{"owner": owner, "action": "Talk to her this week",
                                 "evidence": evidence}]}

    def test_only_the_users_turns_are_kept_under_mic_and_under_their_name(self):
        for speaker in ("Mic", SELF):
            kept = mr.narrow_commitment_evidence(self.memory(SELF, speaker))
            self.assertEqual(kept["commitments"][0]["evidence"],
                             "and talk to her this week for sure", speaker)

    def test_other_owners_are_left_alone(self):
        memory = self.memory("Sam", "Mic")
        before = copy.deepcopy(memory)
        self.assertEqual(mr.narrow_commitment_evidence(memory), before)


class NextStepOwnerTests(unittest.TestCase):
    def owners(self, transcript, evidence):
        reply = json.dumps({"next_steps": [{
            "owner": "Mic", "task": "send the budget file over", "evidence": evidence}]})
        steps = nsp.extract_next_steps(transcript, "Sync", lambda *a, **k: reply, SELF)
        return [step["owner"] for step in steps]

    def test_the_users_task_stays_theirs_when_they_said_it(self):
        quote = "I will send the budget file over tomorrow"
        for speaker in ("Mic", SELF):
            text = f"[00:05] **{speaker}**\n\n{quote}.\n"
            self.assertEqual(self.owners(text, quote), [SELF], speaker)

    def test_the_owner_is_cleared_when_someone_else_said_it(self):
        quote = "I will send the budget file over tomorrow"
        for speaker in ("Remote", OTHER):
            text = f"[00:05] **{speaker}**\n\n{quote}.\n"
            self.assertEqual(self.owners(text, quote), [""], speaker)


class NextStepPromptTests(unittest.TestCase):
    LEGACY = "[00:05] **Mic**\n\nhi\n\n[00:09] **Remote**\n\nyo\n"
    NAMED = "[00:05] **Pat Lee**\n\nhi\n\n[00:09] **Unidentified**\n\nyo\n"

    def test_legacy_transcripts_keep_the_old_wording(self):
        prompt = nsp._prompt("Sync", self.LEGACY, "Sam")
        self.assertIn('"Mic" is the user (Sam)', prompt)
        self.assertIn('If the speaker is\n  "Mic", use Sam', prompt)

    def test_named_transcripts_get_the_name_wording(self):
        prompt = nsp._prompt("Sync", self.NAMED, "Sam")
        self.assertNotIn('"Remote" is one or more', prompt)
        self.assertIn("name on that turn", prompt)
        self.assertIn("Sam is the user", prompt)

    def test_unidentified_is_never_an_owner(self):
        self.assertEqual(nsp._clean_owner("Unidentified", "Sam"), "")
        self.assertEqual(nsp._clean_owner("Pat Lee", "Sam"), "Pat Lee")


if __name__ == "__main__":
    unittest.main()
