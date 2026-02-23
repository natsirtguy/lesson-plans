#!/usr/bin/env python3
"""One-time migration: convert docs/lesson-audit-tracker.md to docs/lesson-audit.json.

Parses all audit table rows, matches lesson names to actual files on disk,
deduplicates (keeping the latest entry), and writes a clean JSON file keyed
by relative path from docs/lessons/.
"""

import json
import re
from pathlib import Path

TRACKER_MD = Path("docs/lesson-audit-tracker.md")
LESSONS_DIR = Path("docs/lessons")
OUTPUT_JSON = Path("docs/lesson-audit.json")


def normalize_title_to_filename(title: str) -> str:
    """Convert a tracker title to the expected filename (lowercase, hyphens)."""
    name = title.lower()
    name = re.sub(r"[(),/'\s]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-") + ".md"


def build_file_index() -> dict[str, str]:
    """Build an index of all lesson files: filename -> relative path."""
    index = {}
    for queue_dir in ("knowledge", "physical"):
        d = LESSONS_DIR / queue_dir
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.suffix == ".md":
                index[f.name] = f"{queue_dir}/{f.name}"
    return index


MANUAL_OVERRIDES = {
    "repetitive-designs-social-sequences-learning-systems.md":
        "knowledge/pattern-recognition-and-creation-physical-rhythms-creative-designs-social-sequences-learning-systems.md",
    "exploration-and-investigation-physical-world-discovery....md":
        "knowledge/exploration-and-investigation-physical-world-discovery-creative-materials-social-interactions-learning-environments.md",
    "patterns-and-systems-mathematical-natural-social-thinking-patterns.md":
        "knowledge/patterns-and-systems-mathematical-patterns-natural-patterns-social-patterns-thinking-patterns.md",
    "time-and-duration-physical-cycles-sequences-measurement.md":
        "knowledge/time-and-duration-physical-cycles-human-experience-sequences-measurement.md",
}


def find_best_match(filename: str, queue_hint: str, file_index: dict[str, str]) -> str | None:
    """Find the best matching file for a normalized filename.

    Tries manual overrides, exact match, prefix match, then apostrophe normalization.
    """
    if filename in MANUAL_OVERRIDES:
        return MANUAL_OVERRIDES[filename]

    # Exact match
    if filename in file_index:
        return file_index[filename]

    # Prefix match: the tracker often has short titles for long filenames
    prefix = filename.removesuffix(".md")
    candidates = [
        path for fname, path in file_index.items()
        if fname.startswith(prefix) and path.startswith(queue_hint)
    ]
    if len(candidates) == 1:
        return candidates[0]

    # Handle apostrophe in actual filenames (e.g., "others'-feelings")
    for fname, path in file_index.items():
        if path.startswith(queue_hint):
            norm = re.sub(r"[(),/'\s]+", "-", fname.lower())
            norm = re.sub(r"-+", "-", norm).strip("-")
            expected = prefix
            if norm == expected or norm.startswith(expected):
                return path

    return None


def parse_tracker():
    """Parse all audit rows from the markdown tracker."""
    text = TRACKER_MD.read_text()

    pattern = re.compile(
        r"^\|\s*(.+?)\s*\|\s*(Knowledge|Physical)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|",
        re.MULTILINE,
    )

    rows = []
    for match in pattern.finditer(text):
        lesson = match.group(1).strip()
        queue = match.group(2).strip()
        verdict = match.group(3).strip()
        issues = match.group(4).strip()
        fixed = match.group(5).strip()

        if lesson in ("Lesson", "--------", ""):
            continue

        rows.append({
            "title": lesson,
            "queue": queue,
            "verdict": verdict,
            "issues": issues,
            "fixed": fixed,
        })

    return rows


def main():
    rows = parse_tracker()
    file_index = build_file_index()
    print(f"Parsed {len(rows)} audit rows from markdown")
    print(f"Found {len(file_index)} lesson files on disk")

    audited = {}
    duplicates = []
    unresolved = []

    for row in rows:
        filename = normalize_title_to_filename(row["title"])
        queue_hint = row["queue"].lower()

        rel_path = find_best_match(filename, queue_hint, file_index)
        if not rel_path:
            rel_path = f"{queue_hint}/{filename}"
            unresolved.append((rel_path, row["title"]))

        if rel_path in audited:
            duplicates.append((rel_path, row["title"]))

        audited[rel_path] = {
            "verdict": row["verdict"],
            "issues": row["issues"],
            "fixed": row["fixed"],
        }

    if duplicates:
        print(f"\nDeduplicated {len(duplicates)} re-audited entries (kept latest):")
        for path, title in duplicates:
            print(f"  {path} ({title})")

    if unresolved:
        print(f"\nWARNING: {len(unresolved)} entries could not be matched to files on disk:")
        for path, title in unresolved:
            print(f"  {path} (from '{title}')")

    # Sort by path
    sorted_audited = dict(sorted(audited.items()))

    output = json.dumps(sorted_audited, indent=2, ensure_ascii=False)
    OUTPUT_JSON.write_text(output + "\n")

    valid = sum(1 for k in sorted_audited if (LESSONS_DIR / k).exists())
    print(f"\nWrote {len(sorted_audited)} unique entries to {OUTPUT_JSON}")
    print(f"  {valid} entries point to existing files")
    print(f"  {len(sorted_audited) - valid} entries have no matching file on disk")


if __name__ == "__main__":
    main()
