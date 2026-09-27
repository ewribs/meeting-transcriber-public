import unittest

from query.meeting_selection import (
    select_query_meetings,
)


def _meeting(day: int, topic: str):
    meeting_run = (
        f"2026-01-{day:02d}_Meeting{day}"
    )

    memory = {
        "topics": [
            {
                "topic_key": topic.lower(),
                "topic": topic,
                "summary": f"Discussion about {topic}",
            }
        ],
        "decisions": [],
        "open_questions": [],
        "follow_ups": [],
        "commitments": [],
    }

    selected = {
        "meeting_run": meeting_run,
        "display_title": f"Meeting {day}",
        "participants": ["Alex"],
        "relevance_weight": 3,
    }

    return (
        (meeting_run, memory),
        selected,
    )


def _history(count: int = 12):
    memories = []
    selected = []

    for day in range(1, count + 1):
        topic = (
            "Vendor Alpha licensing"
            if day in (2, 4, 7)
            else f"General topic {day}"
        )

        memory, item = _meeting(
            day,
            topic,
        )

        memories.append(memory)
        selected.append(item)

    return memories, selected


class MeetingSelectionTests(unittest.TestCase):
    def test_topic_query_keeps_relevant_meetings_and_recent_context(self):
        memories, selected = _history()

        chosen_memories, chosen_selected = (
            select_query_meetings(
                "What changed with Vendor Alpha licensing?",
                memories,
                selected,
                max_meetings=6,
            )
        )

        chosen_runs = {
            run
            for run, _ in chosen_memories
        }

        self.assertEqual(
            len(chosen_memories),
            6,
        )
        self.assertIn(
            "2026-01-02_Meeting2",
            chosen_runs,
        )
        self.assertIn(
            "2026-01-04_Meeting4",
            chosen_runs,
        )
        self.assertIn(
            "2026-01-07_Meeting7",
            chosen_runs,
        )
        self.assertIn(
            "2026-01-12_Meeting12",
            chosen_runs,
        )

        weighted = {
            item["meeting_run"]: item[
                "relevance_weight"
            ]
            for item in chosen_selected
        }

        self.assertGreater(
            weighted["2026-01-07_Meeting7"],
            3,
        )

    def test_generic_query_prefers_most_recent_meetings(self):
        memories, selected = _history()

        chosen_memories, _ = (
            select_query_meetings(
                "What should I focus on?",
                memories,
                selected,
                max_meetings=5,
            )
        )

        self.assertEqual(
            [
                run
                for run, _ in chosen_memories
            ],
            [
                "2026-01-08_Meeting8",
                "2026-01-09_Meeting9",
                "2026-01-10_Meeting10",
                "2026-01-11_Meeting11",
                "2026-01-12_Meeting12",
            ],
        )

    def test_broad_history_request_keeps_all_meetings(self):
        memories, selected = _history()

        chosen_memories, chosen_selected = (
            select_query_meetings(
                "Give me the full history over time.",
                memories,
                selected,
                max_meetings=5,
            )
        )

        self.assertEqual(
            chosen_memories,
            memories,
        )
        self.assertEqual(
            len(chosen_selected),
            len(selected),
        )

    def test_selection_does_not_mutate_original_metadata(self):
        memories, selected = _history()

        original_weights = [
            item["relevance_weight"]
            for item in selected
        ]

        select_query_meetings(
            "Vendor Alpha licensing",
            memories,
            selected,
            max_meetings=5,
        )

        self.assertEqual(
            [
                item["relevance_weight"]
                for item in selected
            ],
            original_weights,
        )


if __name__ == "__main__":
    unittest.main()
