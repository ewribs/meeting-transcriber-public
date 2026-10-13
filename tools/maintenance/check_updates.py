"""Report which project tools and models have newer versions available.

READ-ONLY: this script never installs, upgrades, or downloads anything.
It checks:
  * Homebrew tools the project uses (ffmpeg, whisper-cpp, ollama, python@3.13)
  * Python packages in the active environment (mlx, mlx-lm, Markdown, ...)
  * the MLX language model and the Whisper model against Hugging Face
  * Xcode (version only)

Each line is OK, UPDATE, or UNKNOWN (could not check). Exit code is always 0.
"""

import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

BREW_WATCH = ("ffmpeg", "whisper-cpp", "ollama", "python@3.13")
PIP_WATCH = ("mlx", "mlx-lm", "mlx-metal", "markdown")
HF_API = "https://huggingface.co/api/models/"


def _run(cmd, timeout=120):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return done.returncode, done.stdout
    except Exception as exc:  # missing tool, timeout, ...
        return 1, str(exc)


def _get_json(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ---- pure helpers (unit tested) -------------------------------------------

def parse_brew_outdated(text, watch=BREW_WATCH):
    """Return [(name, installed, current)] for watched formulae that are outdated."""
    data = json.loads(text or "{}")
    rows = []
    for item in data.get("formulae", []):
        if item.get("name") in watch:
            installed = ", ".join(item.get("installed_versions") or []) or "?"
            rows.append((item["name"], installed, item.get("current_version", "?")))
    return rows


def parse_pip_outdated(text, watch=PIP_WATCH):
    """Return [(name, installed, latest)] for watched packages that are outdated."""
    data = json.loads(text or "[]")
    return [
        (p["name"], p.get("version", "?"), p.get("latest_version", "?"))
        for p in data
        if str(p.get("name", "")).lower() in watch
    ]


def local_hf_revision(model_id, cache_root=None):
    """Commit hash of the locally cached snapshot of a Hugging Face model, or None."""
    root = Path(cache_root) if cache_root else Path.home() / ".cache" / "huggingface" / "hub"
    ref = root / ("models--" + model_id.replace("/", "--")) / "refs" / "main"
    try:
        return ref.read_text().strip() or None
    except OSError:
        return None


def find_lfs_sha256(tree, filename):
    """Pull the sha256 of a file out of a Hugging Face 'tree' listing."""
    for entry in tree:
        if entry.get("path") == filename:
            return (entry.get("lfs") or {}).get("oid")
    return None


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ---- checks ---------------------------------------------------------------

def check_brew():
    rc, _ = _run(["brew", "--version"])
    if rc != 0:
        return [("UNKNOWN", "Homebrew", "brew not found")]
    rc, out = _run(["brew", "outdated", "--json=v2"])
    if rc != 0:
        return [("UNKNOWN", "Homebrew", "could not run 'brew outdated'")]
    rows = parse_brew_outdated(out)
    if not rows:
        return [("OK", "Homebrew tools", "ffmpeg, whisper-cpp, ollama, python@3.13 up to date")]
    return [("UPDATE", name, f"{old} -> {new}") for name, old, new in rows]


def check_pip():
    rc, out = _run([sys.executable, "-m", "pip", "list", "--outdated", "--format=json"])
    if rc != 0:
        return [("UNKNOWN", "Python packages", "could not run pip")]
    rows = parse_pip_outdated(out)
    if not rows:
        return [("OK", "Python packages", "mlx, mlx-lm, Markdown up to date")]
    return [("UPDATE", name, f"{old} -> {new}") for name, old, new in rows]


def check_mlx_model():
    try:
        from config import MLX_MODEL
    except Exception:
        MLX_MODEL = "Qwen/Qwen3-30B-A3B-MLX-6bit"
    local = local_hf_revision(MLX_MODEL)
    if not local:
        return [("UNKNOWN", f"MLX model {MLX_MODEL}", "no local copy found in the Hugging Face cache")]
    try:
        remote = _get_json(HF_API + MLX_MODEL).get("sha")
    except Exception as exc:
        return [("UNKNOWN", f"MLX model {MLX_MODEL}", f"could not reach Hugging Face ({exc})")]
    if remote and remote != local:
        return [("UPDATE", f"MLX model {MLX_MODEL}", f"newer revision {remote[:8]} (you have {local[:8]})")]
    return [("OK", f"MLX model {MLX_MODEL}", f"revision {local[:8]} is current")]


def check_whisper_model():
    try:
        from config import WHISPER_MODEL
    except Exception:
        WHISPER_MODEL = Path.home() / "whisper" / "models" / "ggml-medium.en.bin"
    path = Path(WHISPER_MODEL)
    label = f"Whisper model {path.name}"
    if not path.exists():
        return [("UNKNOWN", label, f"not found at {path}")]
    try:
        tree = _get_json(HF_API + "ggerganov/whisper.cpp/tree/main")
        remote = find_lfs_sha256(tree, path.name)
    except Exception as exc:
        return [("UNKNOWN", label, f"could not reach Hugging Face ({exc})")]
    if not remote:
        return [("UNKNOWN", label, "not listed in the whisper.cpp model repo")]
    if file_sha256(path) == remote:
        return [("OK", label, "matches the current published file")]
    return [("UPDATE", label, "differs from the published file (re-download if you want the latest)")]


def check_xcode():
    rc, out = _run(["xcodebuild", "-version"])
    first = out.strip().splitlines()[0] if rc == 0 and out.strip() else None
    if not first:
        return [("UNKNOWN", "Xcode", "not found")]
    return [("INFO", "Xcode", first + " (update through the App Store)")]


def main() -> int:
    print("Checking for updates (read-only; nothing is installed)...\n")
    results = []
    for check in (check_brew, check_pip, check_mlx_model, check_whisper_model, check_xcode):
        results.extend(check())
    for status, name, detail in results:
        print(f"{status:<8} {name}: {detail}")
    updates = sum(1 for status, *_ in results if status == "UPDATE")
    print(f"\n{updates} update(s) available.")
    if updates:
        print("Upgrade one at a time and re-run the tests and benchmark after each.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
