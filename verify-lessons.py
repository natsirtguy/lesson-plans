#!/usr/bin/env python3
"""Verify that all topics have corresponding lesson plan files with correct naming."""

import os
import re
from pathlib import Path
from topics import KNOWLEDGE_AND_CULTURE_CATEGORIES, PHYSICAL_ACTIVITIES

def topic_to_filename(topic_name):
    """Convert topic name to expected filename."""
    # Keep parentheses content, convert to lowercase, replace spaces/slashes/parens with hyphens
    name = topic_name.lower()
    # Replace parentheses, commas, and other special chars with hyphens
    name = re.sub(r'[(),/\s]+', '-', name)
    # Replace multiple hyphens with single
    name = re.sub(r'-+', '-', name)
    # Remove leading/trailing hyphens
    name = name.strip('-')
    return f"{name}.md"

def get_all_topics_by_queue():
    """Get all topics organized by queue."""
    # Knowledge & Culture queue now includes both knowledge and arts/culture topics
    knowledge_topics = []
    for category, topics in KNOWLEDGE_AND_CULTURE_CATEGORIES.items():
        knowledge_topics.extend(topics)

    physical_topics = []
    for category, topics in PHYSICAL_ACTIVITIES.items():
        physical_topics.extend(topics)

    return {
        'knowledge': knowledge_topics,
        'physical': physical_topics
    }

def get_existing_files(queue_dir):
    """Get list of existing lesson plan files."""
    path = Path(f"docs/lessons/{queue_dir}")
    if not path.exists():
        return []
    return [f.name for f in path.glob("*.md")]

def main():
    topics_by_queue = get_all_topics_by_queue()

    print("="*80)
    print("LESSON PLAN VERIFICATION")
    print("="*80)

    total_missing = 0
    total_extra = 0

    for queue, topics in topics_by_queue.items():
        print(f"\n{queue.upper()} QUEUE")
        print("-"*80)

        expected_files = set()
        topic_to_file_map = {}

        for topic in topics:
            filename = topic_to_filename(topic)
            expected_files.add(filename)
            topic_to_file_map[filename] = topic

        existing_files = set(get_existing_files(queue))

        missing = expected_files - existing_files
        extra = existing_files - expected_files

        print(f"Expected: {len(expected_files)}")
        print(f"Found: {len(existing_files)}")
        print(f"Missing: {len(missing)}")
        print(f"Extra: {len(extra)}")

        if missing:
            print(f"\nMISSING FILES ({len(missing)}):")
            for filename in sorted(missing):
                topic = topic_to_file_map[filename]
                print(f"  - {filename}")
                print(f"    Topic: {topic}")

        if extra:
            print(f"\nEXTRA FILES ({len(extra)}):")
            for filename in sorted(extra):
                print(f"  - {filename}")

        total_missing += len(missing)
        total_extra += len(extra)

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total missing files: {total_missing}")
    print(f"Total extra files: {total_extra}")

    if total_missing == 0 and total_extra == 0:
        print("\n✅ ALL TOPICS HAVE MATCHING LESSON PLANS!")
    else:
        print("\n⚠️  MISMATCHES FOUND - NEEDS ATTENTION")

    return 0 if (total_missing == 0 and total_extra == 0) else 1

if __name__ == "__main__":
    exit(main())
