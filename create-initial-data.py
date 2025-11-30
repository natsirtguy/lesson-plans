#!/usr/bin/env python3
"""
Create initial-data.json for the lesson plan PWA.
Puts topics with existing lesson plans at the front of each queue.
"""

import json
import os
from pathlib import Path
from topics import KNOWLEDGE_CATEGORIES, ACTIVITY_CATEGORIES, PHYSICAL_ACTIVITIES

def slugify(text):
    """Convert topic name to filename format."""
    # Remove punctuation and convert to lowercase with hyphens
    slug = text.lower()
    # Remove special characters but keep spaces and hyphens
    slug = ''.join(c if c.isalnum() or c in ' -' else '' for c in slug)
    # Replace multiple spaces with single space, then spaces with hyphens
    slug = '-'.join(slug.split())
    # Remove multiple consecutive hyphens
    while '--' in slug:
        slug = slug.replace('--', '-')
    return slug.strip('-')

def get_possible_slugs(topic_name):
    """Get all possible filename variations for a topic."""
    slugs = set()

    # Full name slugified
    slugs.add(slugify(topic_name))

    # Try without parenthetical content
    if '(' in topic_name:
        base_name = topic_name.split('(')[0].strip()
        slugs.add(slugify(base_name))

    return slugs

def collect_topics_by_queue():
    """Organize all topics by queue type with IDs."""
    topics = {
        'knowledge': [],
        'arts': [],
        'physical': []
    }

    topic_id = 1

    # Knowledge topics
    for category, topic_list in KNOWLEDGE_CATEGORIES.items():
        for topic_name in topic_list:
            topics['knowledge'].append({
                'id': topic_id,
                'name': topic_name,
                'category': category
            })
            topic_id += 1

    # Arts & Culture topics
    for category, topic_list in ACTIVITY_CATEGORIES.items():
        for topic_name in topic_list:
            topics['arts'].append({
                'id': topic_id,
                'name': topic_name,
                'category': category
            })
            topic_id += 1

    # Physical topics
    for category, topic_list in PHYSICAL_ACTIVITIES.items():
        for topic_name in topic_list:
            topics['physical'].append({
                'id': topic_id,
                'name': topic_name,
                'category': category
            })
            topic_id += 1

    return topics

def find_existing_lessons():
    """Find all lesson plan files and map them to topics."""
    lessons_dir = Path('lessons')
    existing = {
        'knowledge': set(),
        'arts': set(),
        'physical': set()
    }

    for queue_type in ['knowledge', 'arts', 'physical']:
        queue_dir = lessons_dir / queue_type
        if queue_dir.exists():
            for lesson_file in queue_dir.glob('*.md'):
                # Get the filename without extension
                filename = lesson_file.stem
                existing[queue_type].add(filename)

    return existing

def match_topics_to_lessons(topics, existing_lessons):
    """Separate topics into those with lessons and those without."""
    with_lessons = {
        'knowledge': [],
        'arts': [],
        'physical': []
    }
    without_lessons = {
        'knowledge': [],
        'arts': [],
        'physical': []
    }

    for queue_type in ['knowledge', 'arts', 'physical']:
        for topic in topics[queue_type]:
            # Try all possible filename variations
            possible_slugs = get_possible_slugs(topic['name'])

            # Check if any variation matches an existing lesson
            has_lesson = any(slug in existing_lessons[queue_type] for slug in possible_slugs)

            if has_lesson:
                with_lessons[queue_type].append(topic)
            else:
                without_lessons[queue_type].append(topic)

    return with_lessons, without_lessons

def create_initial_data():
    """Create initial-data.json with completed topics first."""

    # Collect all topics
    topics = collect_topics_by_queue()

    # Find existing lesson plans
    existing_lessons = find_existing_lessons()

    # Separate topics
    with_lessons, without_lessons = match_topics_to_lessons(topics, existing_lessons)

    # Print statistics
    print(f"\n📊 Topic Statistics:")
    print(f"  Knowledge: {len(with_lessons['knowledge'])} with lessons, {len(without_lessons['knowledge'])} without")
    print(f"  Arts: {len(with_lessons['arts'])} with lessons, {len(without_lessons['arts'])} without")
    print(f"  Physical: {len(with_lessons['physical'])} with lessons, {len(without_lessons['physical'])} without")

    # Create data structure
    data = {
        'masterLists': {
            'arts': topics['arts'],
            'knowledge': topics['knowledge'],
            'physical': topics['physical']
        },
        'queues': {
            'arts': [],
            'knowledge': [],
            'physical': []
        },
        'completed': [],
        'development': [],
        'cycles': {
            'arts': 1,
            'knowledge': 1,
            'physical': 1
        },
        'version': '1.0'
    }

    # Build queues: topics with lessons first, then others
    import random

    for queue_type in ['knowledge', 'arts', 'physical']:
        # Get IDs of topics with lessons (in order)
        with_lesson_ids = [t['id'] for t in with_lessons[queue_type]]

        # Get IDs of topics without lessons (randomized)
        without_lesson_ids = [t['id'] for t in without_lessons[queue_type]]
        random.shuffle(without_lesson_ids)

        # Combine: with lessons first, then without
        data['queues'][queue_type] = with_lesson_ids + without_lesson_ids

        print(f"\n{queue_type.capitalize()} queue:")
        print(f"  First {len(with_lesson_ids)} topics have lesson plans")
        if with_lesson_ids:
            print(f"  First topic: {topics[queue_type][0]['name']}")

    # Save to file
    output_file = 'docs/initial-data.json'
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\n✅ Created {output_file}")
    print(f"   Total topics: {len(topics['knowledge']) + len(topics['arts']) + len(topics['physical'])}")

if __name__ == '__main__':
    create_initial_data()
