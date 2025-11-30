#!/usr/bin/env python3
"""
Generate lesson plans for all 433 topics using Claude subagents.
Processes in batches to avoid overwhelming the system.
"""

import json
from topics import KNOWLEDGE_CATEGORIES, ACTIVITY_CATEGORIES, PHYSICAL_ACTIVITIES

def collect_all_topics():
    """Collect all topics with their queue type and category."""
    all_topics = []

    # Knowledge topics
    for category, topics in KNOWLEDGE_CATEGORIES.items():
        for topic in topics:
            all_topics.append({
                'name': topic,
                'category': category,
                'queue': 'knowledge',
                'prompt_file': 'prompts/knowledge-prompt.md'
            })

    # Arts & Culture topics
    for category, topics in ACTIVITY_CATEGORIES.items():
        for topic in topics:
            all_topics.append({
                'name': topic,
                'category': category,
                'queue': 'arts',
                'prompt_file': 'prompts/arts-culture-prompt.md'
            })

    # Physical topics
    for category, topics in PHYSICAL_ACTIVITIES.items():
        for topic in topics:
            all_topics.append({
                'name': topic,
                'category': category,
                'queue': 'physical',
                'prompt_file': 'prompts/physical-prompt.md'
            })

    return all_topics

def create_batches(topics, batch_size=30):
    """Split topics into batches."""
    batches = []
    for i in range(0, len(topics), batch_size):
        batches.append(topics[i:i + batch_size])
    return batches

if __name__ == '__main__':
    topics = collect_all_topics()
    batches = create_batches(topics, batch_size=30)

    print(f"Total topics: {len(topics)}")
    print(f"Batches: {len(batches)}")
    print(f"\nBatch breakdown:")
    for i, batch in enumerate(batches, 1):
        queue_counts = {}
        for topic in batch:
            queue_counts[topic['queue']] = queue_counts.get(topic['queue'], 0) + 1
        print(f"  Batch {i}: {len(batch)} topics - {queue_counts}")

    # Save all topics to JSON for reference
    with open('backfill-topics.json', 'w') as f:
        json.dump({
            'total': len(topics),
            'batches': len(batches),
            'batch_size': 30,
            'topics': topics
        }, f, indent=2)

    print(f"\n✅ Saved topic list to backfill-topics.json")
