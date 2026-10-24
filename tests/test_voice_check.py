import json
import subprocess
import unittest

import voice_check as vc


def facts(**changes):
    base = {
        "python": "3.13.1",
        "packages": {name: "1.0" for name in vc.PACKAGES},
        "token": True,
        "models": {repo: "ok" for repo in vc.MODELS},
    }
    base.update(changes)
    return base


def runner_returning(text="", returncode=0, error=None):
    def run(command, **kwargs):
        if error:
            raise error
        return subprocess.CompletedProcess(command, returncode, text, "")
    return run


class DescribeTests(unittest.TestCase):
    def test_everything_ready(self):
        ready, lines = vc.describe(facts())
        self.assertTrue(ready)
        self.assertFalse(any(l.startswith(("MISSING", "ACCEPT", "PROBLEM")) for l in lines))

    def test_missing_package_is_named(self):
        packages = {name: "1.0" for name in vc.PACKAGES}
        packages["pyannote.audio"] = None
        ready, lines = vc.describe(facts(packages=packages))
        self.assertFalse(ready)
        self.assertTrue(any("MISSING  pyannote.audio" in l for l in lines))

    def test_no_login_is_reported_once_with_the_command(self):
        models = {repo: "not_found" for repo in vc.MODELS}
        ready, lines = vc.describe(facts(token=False, models=models))
        self.assertFalse(ready)
        self.assertTrue(any("hf auth login" in l for l in lines))
        self.assertEqual(sum(l.startswith("LOGIN") for l in lines), len(vc.MODELS))

    def test_a_model_page_that_needs_accepting_is_named(self):
        models = {repo: "ok" for repo in vc.MODELS}
        models["pyannote/segmentation-3.0"] = "needs_access"
        ready, lines = vc.describe(facts(models=models))
        self.assertFalse(ready)
        self.assertTrue(any(l.startswith("ACCEPT   pyannote/segmentation-3.0") for l in lines))

    def test_errors_become_one_plain_line(self):
        ready, lines = vc.describe({"error": "nope"})
        self.assertEqual((ready, lines), (False, ["nope"]))
        ready, _ = vc.describe(facts(hub_error="ImportError"))
        self.assertFalse(ready)


class RunCheckTests(unittest.TestCase):
    def test_reads_the_last_line_of_output(self):
        out = "some warning\n" + json.dumps(facts()) + "\n"
        self.assertEqual(vc.run_check("py", runner_returning(out))["python"], "3.13.1")

    def test_problems_running_the_python_are_reported_not_raised(self):
        for runner in (runner_returning(error=FileNotFoundError()),
                       runner_returning(error=subprocess.TimeoutExpired("x", 1)),
                       runner_returning("", returncode=1),
                       runner_returning("not json")):
            self.assertIn("error", vc.run_check("py", runner))

    def test_the_script_never_reads_the_token_value(self):
        self.assertNotIn("print(get_token", vc._SCRIPT)
        self.assertIn("bool(get_token())", vc._SCRIPT)


if __name__ == "__main__":
    unittest.main()
