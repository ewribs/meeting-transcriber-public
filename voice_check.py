"""Check that the voice environment is ready, and say what is missing.

Runs a short script in the voice environment's Python (the one set with
``voice_cli.py set-python``). It checks the packages, whether a Hugging Face
login is present, and whether that login may use each model. It downloads
nothing and sends no audio; the only network traffic is a permission check
with Hugging Face for each model name. The token is never read or printed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import voice_worker

MODELS = (
    voice_worker.DIARIZE_MODEL,
    "pyannote/segmentation-3.0",
    voice_worker.EMBED_MODEL,
)
PACKAGES = ("torch", "pyannote.audio", "numpy", "soundfile", "huggingface_hub")
TIMEOUT_SECONDS = 90

_SCRIPT = r'''
import importlib, json, sys
out = {"python": sys.version.split()[0], "packages": {}, "token": False,
       "models": {}}
for name in json.loads(sys.argv[2]):
    try:
        module = importlib.import_module(name)
        out["packages"][name] = str(getattr(module, "__version__", "installed"))
    except Exception:
        out["packages"][name] = None
try:
    from huggingface_hub import HfApi, get_token
    out["token"] = bool(get_token())
    api = HfApi()
    for repo in json.loads(sys.argv[1]):
        try:
            api.auth_check(repo)
            out["models"][repo] = "ok"
        except Exception as error:
            kind = type(error).__name__
            if "Gated" in kind:
                out["models"][repo] = "needs_access"
            elif "NotFound" in kind:
                out["models"][repo] = "not_found"
            else:
                out["models"][repo] = "error"
except Exception as error:
    out["hub_error"] = type(error).__name__
print(json.dumps(out))
'''


def run_check(python_path: str | Path, runner=subprocess.run) -> dict:
    """The raw facts from the voice environment, or {"error": ...}."""
    try:
        result = runner(
            [str(python_path), "-c", _SCRIPT, json.dumps(list(MODELS)),
             json.dumps(list(PACKAGES))],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except FileNotFoundError:
        return {"error": f"The voice Python was not found: {python_path}"}
    except subprocess.TimeoutExpired:
        return {"error": "The check took too long. Check your network connection."}
    if result.returncode != 0:
        return {"error": "The voice Python could not run the check."}
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": "The voice Python gave an unreadable answer."}


def describe(facts: dict) -> tuple[bool, list[str]]:
    """(ready, plain-language lines) for a result of run_check."""
    if "error" in facts:
        return False, [facts["error"]]
    lines = [f"Python {facts['python']}"]
    ready = True
    for name in PACKAGES:
        version = facts["packages"].get(name)
        if version is None:
            ready = False
            lines.append(f"MISSING  {name}  (install it in the voice environment)")
        else:
            lines.append(f"ok       {name} {version}")
    if "hub_error" in facts:
        return False, lines + ["Could not check Hugging Face access."]
    if not facts["token"]:
        ready = False
        lines.append("MISSING  Hugging Face login  (run: hf auth login, in the "
                     "voice environment)")
    for repo in MODELS:
        state = facts["models"].get(repo, "error")
        if state == "ok":
            lines.append(f"ok       {repo}")
        elif state == "needs_access":
            ready = False
            lines.append(f"ACCEPT   {repo}  (open huggingface.co/{repo} while "
                         "signed in and accept its conditions)")
        elif state == "not_found" and not facts["token"]:
            ready = False
            lines.append(f"LOGIN    {repo}  (log in first)")
        else:
            ready = False
            lines.append(f"PROBLEM  {repo}  (not reachable; check your network "
                         "and login)")
    return ready, lines
