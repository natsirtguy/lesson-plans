#!/usr/bin/env python3
"""Build a materials index JSON from lesson plan markdown files.

Extracts the '### Materials Needed' section from each lesson plan and creates
a searchable index mapping topic IDs to their materials text.

Output: docs/materials-index.json
"""

import json
import os
import re

DOCS_DIR = os.path.join(os.path.dirname(__file__), '..', 'docs')
LESSONS_DIR = os.path.join(DOCS_DIR, 'lessons')
INITIAL_DATA = os.path.join(DOCS_DIR, 'initial-data.json')
OUTPUT_FILE = os.path.join(DOCS_DIR, 'materials-index.json')


def topic_name_to_filename(name):
    """Convert topic name to filename format (mirrors JS logic in index.html)."""
    filename = name.lower()
    filename = re.sub(r'[^\w\s-]', ' ', filename)
    filename = filename.strip()
    filename = re.sub(r'\s+', '-', filename)
    filename = re.sub(r'-+', '-', filename)
    filename = filename.strip('-')
    return filename


def extract_materials(filepath):
    """Extract the Materials/Equipment section from a lesson plan markdown file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except (FileNotFoundError, IOError):
        return None

    # Try multiple heading patterns used across lesson types
    patterns = [
        r'###\s+Materials\s+(?:Needed|Required)\s*\n(.*?)(?=\n###\s|\n##\s|\Z)',
        r'###\s+Materials\s*\n(.*?)(?=\n###\s|\n##\s|\Z)',
        r'###\s+Equipment\s+(?:Needed|Required)\s*\n(.*?)(?=\n###\s|\n##\s|\Z)',
        r'###\s+Equipment\s*\n(.*?)(?=\n###\s|\n##\s|\Z)',
    ]
    match = None
    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            break
    if not match:
        return None

    materials_text = match.group(1).strip()
    # Extract just the item names from bullet points, stripping markdown formatting
    items = []
    for line in materials_text.split('\n'):
        line = line.strip()
        if line.startswith('- ') or line.startswith('* '):
            item = line[2:].strip()
            # Remove markdown bold
            item = re.sub(r'\*\*([^*]+)\*\*', r'\1', item)
            items.append(item)
        elif line.startswith('**') and ':' in line:
            # Lines like "**Essential**:" or "**Cost**: ..."
            continue

    return ' | '.join(items) if items else materials_text[:200]


def main():
    with open(INITIAL_DATA, 'r', encoding='utf-8') as f:
        data = json.load(f)

    index = {}  # topic_id -> materials text
    found = 0
    missing = 0

    for queue in ['knowledge', 'physical', 'songs']:
        topics = data['masterLists'].get(queue, [])
        for topic in topics:
            filename = topic_name_to_filename(topic['name'])
            filepath = os.path.join(LESSONS_DIR, queue, f'{filename}.md')
            materials = extract_materials(filepath)
            if materials:
                index[str(topic['id'])] = materials
                found += 1
            else:
                missing += 1

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, separators=(',', ':'))

    print(f'Materials index built: {found} topics indexed, {missing} without materials')
    print(f'Output: {OUTPUT_FILE}')
    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f'File size: {size_kb:.1f} KB')


if __name__ == '__main__':
    main()
