#!/usr/bin/env python3
"""Select a random batch of unaudited lesson plans for the next intellectual rigor audit.

Uses docs/lesson-audit.json as the source of truth for what's already been audited,
and scans docs/lessons/ on disk for the full set of lesson files.

Usage:
    python select-audit-batch.py              # 25 random unaudited lessons
    python select-audit-batch.py 10           # 10 random unaudited lessons
    python select-audit-batch.py --all        # list all unaudited lessons
"""

import json
import random
import signal
import sys
from pathlib import Path

signal.signal(signal.SIGPIPE, signal.SIG_DFL)

AUDIT_JSON = Path("docs/lesson-audit.json")
LESSONS_DIR = Path("docs/lessons")


def load_audited(audit_path: Path) -> set[str]:
    """Load the set of already-audited relative paths from the JSON tracker."""
    if not audit_path.exists():
        return set()
    data = json.loads(audit_path.read_text())
    return set(data.keys())


def get_all_lesson_files() -> list[tuple[str, str]]:
    """Return (queue, relative_path) for every lesson file on disk.

    relative_path is relative to docs/lessons/ (e.g. "knowledge/topic.md").
    """
    lessons = []
    for queue in ("knowledge", "physical"):
        d = LESSONS_DIR / queue
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix == ".md":
                lessons.append((queue, f"{queue}/{f.name}"))
    return lessons


def main():
    batch_size = 25
    show_all = False

    if len(sys.argv) > 1:
        if sys.argv[1] == "--all":
            show_all = True
        else:
            try:
                batch_size = int(sys.argv[1])
            except ValueError:
                print(f"Usage: {sys.argv[0]} [BATCH_SIZE | --all]")
                sys.exit(1)

    audited = load_audited(AUDIT_JSON)
    all_lessons = get_all_lesson_files()

    unaudited = [(q, p) for q, p in all_lessons if p not in audited]
    knowledge_unaudited = [l for l in unaudited if l[0] == "knowledge"]
    physical_unaudited = [l for l in unaudited if l[0] == "physical"]

    print(f"Total lesson files:     {len(all_lessons)}")
    print(f"Already audited:        {len(audited)}")
    print(f"Remaining unaudited:    {len(unaudited)}")
    print(f"  Knowledge:            {len(knowledge_unaudited)}")
    print(f"  Physical:             {len(physical_unaudited)}")
    print()

    if show_all:
        print("=== All Unaudited Lessons ===")
        print()
        for queue, path in unaudited:
            print(f"  [{queue:10s}] {path}")
        return

    if len(unaudited) == 0:
        print("All lessons have been audited!")
        return

    selected = random.sample(unaudited, min(batch_size, len(unaudited)))
    knowledge_selected = [l for l in selected if l[0] == "knowledge"]
    physical_selected = [l for l in selected if l[0] == "physical"]

    print(f"=== Random Batch of {len(selected)} for Next Audit ===")
    print()

    if knowledge_selected:
        print(f"Knowledge ({len(knowledge_selected)}):")
        for _, path in knowledge_selected:
            print(f"  docs/lessons/{path}")
        print()

    if physical_selected:
        print(f"Physical ({len(physical_selected)}):")
        for _, path in physical_selected:
            print(f"  docs/lessons/{path}")
        print()

    print("=== Copy-paste file paths ===")
    for _, path in selected:
        print(f"docs/lessons/{path}")


if __name__ == "__main__":
    main()
