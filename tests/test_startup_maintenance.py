import unittest

from startup_maintenance import run_startup_retention


class StartupMaintenanceTests(unittest.TestCase):
    def test_runs_local_and_archived_retention_in_delete_mode(self):
        calls = []

        def local_cleanup(*, days, delete):
            calls.append(("local", days, delete))
            return {
                "eligible": [("a", "archive")],
                "skipped": [("b", "reason")],
                "deleted": 1,
                "deleted_bytes": 123,
                "days": days,
            }

        def archived_cleanup(*, days, delete):
            calls.append(("archived", days, delete))
            return {
                "eligible": [],
                "skipped": [],
                "deleted": 0,
                "deleted_bytes": 0,
                "days": days,
                "forever": False,
            }

        payload = run_startup_retention(
            local_days=30,
            archived_days=365,
            local_cleanup=local_cleanup,
            archived_cleanup=archived_cleanup,
        )

        self.assertEqual(calls, [("local", 30, True), ("archived", 365, True)])
        self.assertEqual(payload["local"]["deleted"], 1)
        self.assertEqual(payload["local"]["skipped"], 1)
        self.assertEqual(payload["warnings"], [])

    def test_archive_forever_skips_archived_cleanup(self):
        def local_cleanup(*, days, delete):
            return {
                "eligible": [],
                "skipped": [],
                "deleted": 0,
                "deleted_bytes": 0,
                "days": days,
            }

        def archived_cleanup(**kwargs):  # pragma: no cover - should never run
            raise AssertionError("archived cleanup should not run")

        payload = run_startup_retention(
            local_days=30,
            archived_days=0,
            local_cleanup=local_cleanup,
            archived_cleanup=archived_cleanup,
        )

        self.assertTrue(payload["archived"]["forever"])
        self.assertEqual(payload["warnings"], [])

    def test_cleanup_failures_are_warnings_not_startup_errors(self):
        def local_cleanup(**kwargs):
            raise RuntimeError("archive offline")

        def archived_cleanup(**kwargs):
            raise RuntimeError("archive offline")

        payload = run_startup_retention(
            local_days=30,
            archived_days=365,
            local_cleanup=local_cleanup,
            archived_cleanup=archived_cleanup,
        )

        self.assertEqual(payload["local"]["deleted"], 0)
        self.assertEqual(payload["archived"]["deleted"], 0)
        self.assertEqual(len(payload["warnings"]), 2)
        self.assertIn("archive offline", payload["warnings"][0])


if __name__ == "__main__":
    unittest.main()
