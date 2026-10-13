"""Upgrade ONE project tool at a time, with a before/after safety check.

Usage:
    python3 tools/maintenance/upgrade_tool.py            (shows a numbered menu)
    python3 tools/maintenance/upgrade_tool.py COMPONENT [--cases a,b,c] [--yes]

COMPONENT is one of: mlx-lm, mlx, markdown, ffmpeg, whisper-cpp, ollama, python@3.13

What it does, in order:
  1. runs the checks BEFORE the upgrade;
  2. asks you to confirm, then saves the current version to
     upgrade_snapshots/<time>.json (for rollback) and upgrades only that component;
  3. runs the same checks AFTER and prints a before/after comparison.

Checks: the unit tests always; for the language-model components (mlx-lm, mlx,
ollama) also the private benchmark cases (listed in upgrade_cases.local.txt, or all of them), because those can change extraction results.
For ffmpeg and whisper-cpp it also runs a quick "does it start" check; test one
real recording yourself afterwards.

Nothing is changed unless you answer y at the confirmation.
"""

import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

# component -> (kind, uses_llm, smoke command)
COMPONENTS = {
    "mlx-lm": ("pip", True, None),
    "mlx": ("pip", True, None),
    "markdown": ("pip", False, None),
    "ffmpeg": ("brew", False, ["ffmpeg", "-version"]),
    "whisper-cpp": ("brew", False, ["whisper-cli", "--help"]),
    "ollama": ("brew", True, ["ollama", "--version"]),
    "python@3.13": ("brew", False, None),
}
CASES_FILE = _REPO_ROOT / "upgrade_cases.local.txt"  # private, git-ignored: one case name per line
CASE_ROOT = _REPO_ROOT / "private_benchmarks"
SNAPSHOT_DIR = _REPO_ROOT / "upgrade_snapshots"

_CASE_RE = re.compile(r"^(\S+): (PASS|FAIL) \(")
_CAT_RE = re.compile(r"^\s+(\w+)\s+P=[\d.]+ R=[\d.]+ matched=(\d+)/(\d+) predicted=(\d+)")


# Components that can affect audio handling also get the recording check.
AUDIO_CHECK = ("ffmpeg", "whisper-cpp", "python@3.13")

# ---- pure helpers (unit tested) -------------------------------------------

def latest_recording(meetings_dir):
    """Newest .m4a in the meetings folder, or None."""
    try:
        files = [f for f in Path(meetings_dir).glob("*.m4a") if f.is_file()]
    except OSError:
        return None
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def parse_audio_contract(text):
    """(ok, detail) from the app's 'audio-contract' JSON output."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return False, "no readable result"
    ok = bool(data.get("extraction_ok")) and bool(data.get("compatible"))
    return ok, str(data.get("message", "")) or ("ok" if ok else "not compatible")


def default_cases(cases_file=CASES_FILE, case_root=CASE_ROOT):
    """Cases from the private list file if present, else every case that has an answer key."""
    try:
        names = [l.strip() for l in Path(cases_file).read_text().splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        if names:
            return names
    except OSError:
        pass
    try:
        return sorted(d.name for d in Path(case_root).iterdir()
                      if d.is_dir() and (d / "expected_memory.json").exists())
    except OSError:
        return []


def parse_benchmark_output(text):
    """{case: {"passed": bool, "categories": {name: (matched, expected, predicted)}}}"""
    results, current = {}, None
    for line in text.splitlines():
        m = _CASE_RE.match(line)
        if m:
            current = results.setdefault(m.group(1), {"passed": m.group(2) == "PASS", "categories": {}})
            continue
        m = _CAT_RE.match(line)
        if m and current is not None:
            current["categories"][m.group(1)] = tuple(int(m.group(i)) for i in (2, 3, 4))
    return results


def compare_benchmarks(before, after):
    """Human-readable lines describing what changed between two parsed runs."""
    lines = []
    for case in sorted(set(before) | set(after)):
        b, a = before.get(case), after.get(case)
        if b is None or a is None:
            lines.append(f"{case}: only present in the {'after' if b is None else 'before'} run")
            continue
        if b["passed"] != a["passed"]:
            lines.append(f"{case}: {'PASS' if b['passed'] else 'FAIL'} -> {'PASS' if a['passed'] else 'FAIL'}")
        for cat in sorted(set(b["categories"]) | set(a["categories"])):
            bm, am = b["categories"].get(cat), a["categories"].get(cat)
            if bm != am:
                lines.append(f"{case} / {cat}: matched {bm[0] if bm else '?'} -> {am[0] if am else '?'}, "
                             f"predicted {bm[2] if bm else '?'} -> {am[2] if am else '?'}")
    return lines


def parse_unittest_summary(text):
    """(tests_run, ok, error_names) from unittest output."""
    ran = re.search(r"^Ran (\d+) tests?", text, re.M)
    ok = bool(re.search(r"^OK\b", text, re.M))
    bad = re.findall(r"^(?:FAIL|ERROR): (\S+)", text, re.M)
    return (int(ran.group(1)) if ran else 0, ok, bad)


def rollback_hint(component, kind, old_version):
    if kind == "pip":
        return f"python3 -m pip install '{component}=={old_version}'"
    return ("Homebrew has no simple 'go back' for this tool. If something broke, tell me the symptom and "
            "we'll work out the fix; your old version was " + str(old_version))


def menu_rows(names, versions, outdated):
    """[(number, name, installed, latest_or_None)] in menu order."""
    return [(i, n, versions.get(n), outdated.get(n)) for i, n in enumerate(names, 1)]


def format_menu(rows):
    lines = []
    for number, name, installed, latest in rows:
        if installed is None:
            note = "not installed via Homebrew"
        elif latest:
            note = f"{installed} -> {latest}  UPDATE AVAILABLE"
        else:
            note = f"{installed}  up to date"
        lines.append(f"  {number}) {name:<12} {note}")
    return "\n".join(lines)


def choose_component():
    """Show the menu and return the chosen component name, or None to quit."""
    import check_updates

    names = list(COMPONENTS)
    print("Checking what is installed...\n")
    versions = {n: current_version(n, COMPONENTS[n][0]) for n in names}
    outdated = {}
    try:
        rc, out = _run(["brew", "outdated", "--json=v2"], stdout_only=True)
        if rc == 0:
            for name, _old, new in check_updates.parse_brew_outdated(out, watch=tuple(names)):
                outdated[name] = new
    except Exception as exc:
        print(f"(could not check Homebrew updates: {exc})")
    try:
        rc, out = _run([sys.executable, "-m", "pip", "list", "--outdated", "--format=json"], stdout_only=True)
        if rc == 0:
            for name, _old, new in check_updates.parse_pip_outdated(out, watch=tuple(names)):
                outdated[name.lower()] = new  # pip reports e.g. "Markdown"
    except Exception as exc:
        print(f"(could not check pip updates: {exc})")
    rows = menu_rows(names, versions, outdated)
    print("Which tool do you want to upgrade?\n")
    print(format_menu(rows))
    print("  q) quit\n")
    answer = input("Enter a number: ").strip().lower()
    if answer.isdigit() and 1 <= int(answer) <= len(names):
        return names[int(answer) - 1]
    return None


# ---- running things -------------------------------------------------------

def _run(cmd, timeout=None, stdout_only=False):
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=_REPO_ROOT)
    if stdout_only:  # for JSON: warnings on stderr must not be mixed in
        return done.returncode, done.stdout or ""
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def current_version(component, kind):
    if kind == "pip":
        rc, out = _run([sys.executable, "-m", "pip", "show", component])
        m = re.search(r"^Version: (.+)$", out, re.M)
        return m.group(1).strip() if rc == 0 and m else None
    rc, out = _run(["brew", "list", "--versions", component])
    return out.strip().split(None, 1)[1] if rc == 0 and " " in out.strip() else None


def run_checks(component, cases):
    kind, uses_llm, smoke = COMPONENTS[component]
    result = {"tests": None, "smoke": None, "benchmark": None, "audio": None}
    print("  running unit tests...")
    rc, out = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests"])
    result["tests"] = parse_unittest_summary(out)
    if smoke:
        print("  running quick start check...")
        rc, _ = _run(smoke, timeout=60)
        result["smoke"] = (rc == 0)
    if component in AUDIO_CHECK:
        print("  checking the channel split on your newest recording...")
        try:
            from config import MEETINGS_DIR
        except Exception:
            MEETINGS_DIR = _REPO_ROOT / "meetings"
        recording = latest_recording(MEETINGS_DIR)
        if recording is None:
            result["audio"] = (None, "no .m4a recording found to test")
        else:
            rc, out = _run([sys.executable, "backend_bridge.py", "audio-contract", str(recording)])
            result["audio"] = parse_audio_contract(out) if rc == 0 else (False, "the check could not run")
    if uses_llm and cases:
        print(f"  running benchmark cases ({', '.join(cases)}) - this takes several minutes each...")
        parsed = {}
        for case in cases:
            _, out = _run([sys.executable, "tools/benchmark/memory_benchmark.py", "run",
                           "--case", case, "--production-parity"])
            parsed.update(parse_benchmark_output(out))
        result["benchmark"] = parsed
    return result


def describe(result):
    lines = []
    ran, ok, bad = result["tests"]
    lines.append(f"unit tests: {'OK' if ok else 'PROBLEMS'} ({ran} run" + (f", failing: {', '.join(bad)}" if bad else "") + ")")
    if result["smoke"] is not None:
        lines.append(f"starts correctly: {'yes' if result['smoke'] else 'NO'}")
    if result["audio"] is not None:
        ok, detail = result["audio"]
        label = "OK" if ok else ("skipped" if ok is None else "PROBLEM")
        lines.append(f"recording channel split: {label} ({detail})")
    for case, data in (result["benchmark"] or {}).items():
        lines.append(f"benchmark {case}: {'PASS' if data['passed'] else 'FAIL'}")
    return lines


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Upgrade one tool with a before/after check.")
    p.add_argument("component", nargs="?", choices=sorted(COMPONENTS))
    p.add_argument("--cases", default=None, help="benchmark cases (comma separated); default: upgrade_cases.local.txt, else all")
    p.add_argument("--yes", action="store_true", help="skip the confirmation question")
    args = p.parse_args(argv)

    if args.component is None:
        args.component = choose_component()
        if args.component is None:
            print("Nothing selected. Nothing changed.")
            return 0
    kind, uses_llm, _ = COMPONENTS[args.component]
    cases = [c for c in args.cases.split(",") if c] if args.cases else default_cases()
    old = current_version(args.component, kind)
    if old is None:
        print(f"Could not find an installed version of {args.component}. Nothing changed.")
        return 1

    print("BEFORE the upgrade:")
    before = run_checks(args.component, cases)
    for line in describe(before):
        print("  " + line)
    if not before["tests"][1]:
        print("\nThe tests are not passing before the upgrade, so a before/after comparison would mean "
              "nothing. Nothing changed. Fix those first.")
        return 1

    if not args.yes and input(f"\nUpgrade {args.component} from {old}? [y/N] ").strip().lower() != "y":
        print("Cancelled. Nothing changed.")
        return 0

    SNAPSHOT_DIR.mkdir(exist_ok=True)
    snap = SNAPSHOT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{args.component.replace('@', '_')}.json"
    snap.write_text(json.dumps({"component": args.component, "kind": kind, "version": old}, indent=2))
    print(f"\nSaved current version ({args.component} {old}) to {snap.name}")

    cmd = ([sys.executable, "-m", "pip", "install", "--upgrade", args.component] if kind == "pip"
           else ["brew", "upgrade", args.component])
    print("Running: " + " ".join(cmd))
    rc, out = _run(cmd)
    if rc != 0:
        print(out[-1500:])
        print("The upgrade command failed. Rollback: " + rollback_hint(args.component, kind, old))
        return 1
    new = current_version(args.component, kind)
    print(f"Upgraded {args.component}: {old} -> {new}\n")

    print("AFTER the upgrade:")
    after = run_checks(args.component, cases)
    for line in describe(after):
        print("  " + line)

    problems = []
    if not after["tests"][1]:
        problems.append("unit tests no longer pass")
    if after["audio"] is not None and after["audio"][0] is False:
        problems.append("the recording channel split check failed")
    if after["smoke"] is False:
        problems.append("the tool no longer starts")
    changes = compare_benchmarks(before["benchmark"] or {}, after["benchmark"] or {})
    print("\nBenchmark differences:" if changes else "\nBenchmark: no differences." if before["benchmark"] else "")
    for line in changes:
        print("  " + line)
    if any(" PASS -> FAIL" in c for c in changes):
        problems.append("a benchmark case went from PASS to FAIL")

    if problems:
        print("\nPROBLEMS: " + "; ".join(problems))
        print("Rollback: " + rollback_hint(args.component, kind, old))
    else:
        print("\nNo problems found. Keep it." + (" Also test one real recording." if args.component in ("ffmpeg", "whisper-cpp") else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
