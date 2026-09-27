import tempfile
import unittest
from pathlib import Path

from execution_telemetry import (
    MAX_TELEMETRY_RECORDS,
    build_execution_record,
    load_execution_telemetry,
    record_execution_telemetry,
)


class ExecutionTelemetryTests(unittest.TestCase):
    def test_record_whitelists_execution_fields(self):
        metadata = {
            "profile": "Balanced",
            "mode": "direct",
            "estimated_prompt_tokens": 4321,
            "model_name": "qwen3:8b",
            "hardware_label": "Apple M2 Pro · 16 GB",
            "user_prompt": "SECRET PROMPT",
            "meeting_title": "SECRET MEETING",
            "response": "SECRET RESPONSE",
        }

        record = build_execution_record(
            metadata,
            elapsed_seconds=12.3456,
        )

        self.assertEqual(
            record["elapsed_seconds"],
            12.346,
        )
        self.assertEqual(
            record["profile"],
            "Balanced",
        )
        self.assertNotIn(
            "user_prompt",
            record,
        )
        self.assertNotIn(
            "meeting_title",
            record,
        )
        self.assertNotIn(
            "response",
            record,
        )

    def test_record_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.jsonl"

            record_execution_telemetry(
                {
                    "profile": "Balanced",
                    "mode": "direct",
                    "inference_calls": 1,
                },
                elapsed_seconds=9.5,
                telemetry_path=path,
            )

            records = load_execution_telemetry(
                path
            )

            self.assertEqual(len(records), 1)
            self.assertEqual(
                records[0]["mode"],
                "direct",
            )
            self.assertEqual(
                records[0]["elapsed_seconds"],
                9.5,
            )

    def test_history_is_capped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.jsonl"

            for index in range(
                MAX_TELEMETRY_RECORDS + 7
            ):
                record_execution_telemetry(
                    {
                        "profile": "Balanced",
                        "mode": "direct",
                        "estimated_prompt_tokens": (
                            index
                        ),
                    },
                    elapsed_seconds=1.0,
                    telemetry_path=path,
                )

            records = load_execution_telemetry(
                path
            )

            self.assertEqual(
                len(records),
                MAX_TELEMETRY_RECORDS,
            )
            self.assertEqual(
                records[-1][
                    "estimated_prompt_tokens"
                ],
                MAX_TELEMETRY_RECORDS + 6,
            )

    def test_unreadable_history_returns_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.jsonl"
            path.write_text(
                "not json\n",
                encoding="utf-8",
            )

            self.assertEqual(
                load_execution_telemetry(path),
                [],
            )


if __name__ == "__main__":
    unittest.main()
