#!/usr/bin/env python3
"""Select a random batch of unaudited lesson plans for the next intellectual rigor audit.

Usage:
    python select-audit-batch.py              # 25 random unaudited lessons
    python select-audit-batch.py 10           # 10 random unaudited lessons
    python select-audit-batch.py --all        # list all unaudited lessons
"""

import os
import random
import re
import signal
import sys
from pathlib import Path

signal.signal(signal.SIGPIPE, signal.SIG_DFL)

TRACKER_PATH = Path("docs/lesson-audit-tracker.md")
LESSONS_DIR = Path("docs/lessons")
KNOWLEDGE_DIR = LESSONS_DIR / "knowledge"
PHYSICAL_DIR = LESSONS_DIR / "physical"


def parse_audited_lessons(tracker_path: Path) -> set[str]:
    """Extract already-audited lesson names from the tracker markdown tables."""
    audited = set()
    text = tracker_path.read_text()

    # Match table rows: | Lesson Name | Queue | Verdict | ...
    # Skip header rows (contain "Lesson" or dashes)
    for match in re.finditer(r"^\|\s*(.+?)\s*\|\s*(Knowledge|Physical)\s*\|", text, re.MULTILINE):
        lesson_name = match.group(1).strip()
        if lesson_name in ("Lesson", "--------", ""):
            continue
        audited.add(lesson_name)

    return audited


def lesson_filename_to_title(filename: str) -> str:
    """Convert a filename like 'day-and-night-cycles.md' to a rough title.

    This is used for display only — matching is done by filename.
    """
    name = filename.removesuffix(".md")
    return name.replace("-", " ").title()


def normalize_title_to_filename(title: str) -> str:
    """Convert a tracker title to the expected filename (lowercase, hyphens)."""
    name = title.lower()
    name = re.sub(r"[(),/'\s]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-") + ".md"


def get_all_lesson_files() -> list[tuple[str, str, str]]:
    """Return (queue, filename, display_title) for every lesson plan file."""
    lessons = []
    for queue, directory in [("Knowledge", KNOWLEDGE_DIR), ("Physical", PHYSICAL_DIR)]:
        if not directory.exists():
            continue
        for f in sorted(directory.iterdir()):
            if f.suffix == ".md":
                lessons.append((queue, f.name, lesson_filename_to_title(f.name)))
    return lessons


def find_unaudited(all_lessons, audited_names) -> list[tuple[str, str, str]]:
    """Filter to lessons not yet audited.

    Matches by converting audited titles to filenames and comparing.
    """
    audited_filenames = {normalize_title_to_filename(name) for name in audited_names}

    unaudited = []
    for queue, filename, title in all_lessons:
        if filename not in audited_filenames:
            unaudited.append((queue, filename, title))
    return unaudited


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

    if not TRACKER_PATH.exists():
        print(f"Error: Tracker not found at {TRACKER_PATH}")
        sys.exit(1)

    audited_names = parse_audited_lessons(TRACKER_PATH)
    all_lessons = get_all_lesson_files()
    unaudited = find_unaudited(all_lessons, audited_names)

    knowledge_unaudited = [l for l in unaudited if l[0] == "Knowledge"]
    physical_unaudited = [l for l in unaudited if l[0] == "Physical"]

    print(f"Total lesson files:     {len(all_lessons)}")
    print(f"Already audited:        {len(audited_names)}")
    print(f"Remaining unaudited:    {len(unaudited)}")
    print(f"  Knowledge:            {len(knowledge_unaudited)}")
    print(f"  Physical:             {len(physical_unaudited)}")
    print()

    if show_all:
        print("=== All Unaudited Lessons ===")
        print()
        for queue, filename, title in unaudited:
            print(f"  [{queue:10s}] {filename}")
        return

    if len(unaudited) == 0:
        print("All lessons have been audited!")
        return

    # Select random batch, maintaining roughly proportional queue representation
    selected = random.sample(unaudited, min(batch_size, len(unaudited)))

    knowledge_selected = [l for l in selected if l[0] == "Knowledge"]
    physical_selected = [l for l in selected if l[0] == "Physical"]

    print(f"=== Random Batch of {len(selected)} for Next Audit ===")
    print()

    if knowledge_selected:
        print(f"Knowledge ({len(knowledge_selected)}):")
        for _, filename, title in knowledge_selected:
            print(f"  docs/lessons/knowledge/{filename}")
        print()

    if physical_selected:
        print(f"Physical ({len(physical_selected)}):")
        for _, filename, title in physical_selected:
            print(f"  docs/lessons/physical/{filename}")
        print()

    # Output in a format easy to copy-paste into subagent prompts
    print("=== Copy-paste file paths ===")
    for queue, filename, _ in selected:
        q = "knowledge" if queue == "Knowledge" else "physical"
        print(f"/home/user/lesson-plans/docs/lessons/{q}/{filename}")


if __name__ == "__main__":
    main()
