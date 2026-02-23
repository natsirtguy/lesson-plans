#!/usr/bin/env python3
"""Record audit results for one or more lesson plans into docs/lesson-audit.json.

Usage:
    python record-audit-results.py <path> <verdict> <issues> [fixed]

Arguments:
    path      Lesson file path (e.g. docs/lessons/knowledge/topic.md)
    verdict   PASS, FAIL, or "FAIL -> FIXED"
    issues    Brief description of issues found (or why it passed)
    fixed     Brief description of fixes applied (required for FAIL -> FIXED, omit for PASS)

Examples:
    python record-audit-results.py docs/lessons/knowledge/sleep-and-rest.md PASS \
        "Uses real terminology: circadian rhythm, melatonin, REM sleep"

    python record-audit-results.py docs/lessons/knowledge/cooking.md "FAIL -> FIXED" \
        "No food chemistry, purely procedural" \
        "Added chemical reaction, emulsification, dissolve, protein vocabulary"

    python record-audit-results.py docs/lessons/physical/yoga.md FAIL \
        "No anatomy or physiology content"

Batch mode (pipe paths from select-audit-batch.py):
    Not supported — record results one at a time after auditing each lesson.

Checking what's been audited:
    python record-audit-results.py --status               # summary stats
    python record-audit-results.py --check <path>         # check if a specific lesson is audited
"""

import json
import sys
from pathlib import Path

AUDIT_JSON = Path("docs/lesson-audit.json")
LESSONS_DIR = Path("docs/lessons")

VALID_VERDICTS = {"PASS", "FAIL", "FAIL -> FIXED"}


def load_audit_data() -> dict:
    if AUDIT_JSON.exists():
        return json.loads(AUDIT_JSON.read_text())
    return {}


def save_audit_data(data: dict) -> None:
    sorted_data = dict(sorted(data.items()))
    AUDIT_JSON.write_text(json.dumps(sorted_data, indent=2, ensure_ascii=False) + "\n")


def normalize_path(path_str: str) -> str:
    """Convert a file path to the relative key used in audit JSON.

    Accepts: docs/lessons/knowledge/topic.md, knowledge/topic.md,
             /home/.../docs/lessons/knowledge/topic.md
    Returns: knowledge/topic.md
    """
    path = Path(path_str)

    # Strip everything up to and including "docs/lessons/"
    parts = path.parts
    for i, part in enumerate(parts):
        if part == "lessons" and i > 0 and parts[i - 1] == "docs":
            return str(Path(*parts[i + 1:]))

    # If path is already relative like "knowledge/topic.md"
    if len(parts) == 2 and parts[0] in ("knowledge", "physical"):
        return str(path)

    return path_str


def cmd_status():
    data = load_audit_data()
    all_lessons = []
    for queue in ("knowledge", "physical"):
        d = LESSONS_DIR / queue
        if d.exists():
            for f in d.iterdir():
                if f.suffix == ".md":
                    all_lessons.append(f"{queue}/{f.name}")

    audited = set(data.keys())
    unaudited = [p for p in all_lessons if p not in audited]

    verdicts = {}
    for v in data.values():
        verdicts[v["verdict"]] = verdicts.get(v["verdict"], 0) + 1

    print(f"Total lesson files:  {len(all_lessons)}")
    print(f"Audited:             {len(data)}")
    print(f"Remaining:           {len(unaudited)}")
    print(f"Verdicts:            {verdicts}")


def cmd_check(path_str: str):
    data = load_audit_data()
    key = normalize_path(path_str)
    if key in data:
        entry = data[key]
        print(f"AUDITED: {key}")
        print(f"  Verdict: {entry['verdict']}")
        print(f"  Issues:  {entry['issues']}")
        print(f"  Fixed:   {entry['fixed']}")
    else:
        print(f"NOT AUDITED: {key}")


def cmd_record(path_str: str, verdict: str, issues: str, fixed: str):
    key = normalize_path(path_str)

    # Validate the file exists
    full_path = LESSONS_DIR / key
    if not full_path.exists():
        print(f"Error: File not found: {full_path}")
        sys.exit(1)

    # Validate verdict
    if verdict not in VALID_VERDICTS:
        print(f"Error: Invalid verdict '{verdict}'. Must be one of: {VALID_VERDICTS}")
        sys.exit(1)

    # Validate fixed is provided for FAIL -> FIXED
    if verdict == "FAIL -> FIXED" and (not fixed or fixed == "N/A"):
        print("Error: 'fixed' description required for FAIL -> FIXED verdict")
        sys.exit(1)

    data = load_audit_data()

    if key in data:
        print(f"Warning: {key} already audited (verdict: {data[key]['verdict']}). Overwriting.")

    data[key] = {
        "verdict": verdict,
        "issues": issues,
        "fixed": fixed,
    }

    save_audit_data(data)
    print(f"Recorded: {key} -> {verdict}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--status":
        cmd_status()
        return

    if sys.argv[1] == "--check":
        if len(sys.argv) < 3:
            print("Usage: record-audit-results.py --check <path>")
            sys.exit(1)
        cmd_check(sys.argv[2])
        return

    # Record mode: path verdict issues [fixed]
    if len(sys.argv) < 4:
        print("Usage: record-audit-results.py <path> <verdict> <issues> [fixed]")
        print(f"  verdict must be one of: {VALID_VERDICTS}")
        sys.exit(1)

    path_str = sys.argv[1]
    verdict = sys.argv[2]
    issues = sys.argv[3]
    fixed = sys.argv[4] if len(sys.argv) > 4 else "N/A"

    cmd_record(path_str, verdict, issues, fixed)


if __name__ == "__main__":
    main()
