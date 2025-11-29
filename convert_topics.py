#!/usr/bin/env python3
"""
Convert topics.py data to initial-data.json for the lesson plan app.
Maps topic categories to appropriate queues (arts, knowledge, physical).
"""

import json
import random
from topics import KNOWLEDGE_CATEGORIES, ACTIVITY_CATEGORIES, PHYSICAL_ACTIVITIES

def convert_topics():
    """Convert Python dictionaries to JSON data structure."""

    # Initialize
    arts_topics = []
    knowledge_topics = []
    physical_topics = []
    id_counter = 1

    # Convert Knowledge Categories → Knowledge Queue
    for category, topics in KNOWLEDGE_CATEGORIES.items():
        for topic in topics:
            knowledge_topics.append({
                "id": id_counter,
                "name": topic,
                "category": category,
                "sourceCategory": category
            })
            id_counter += 1

    # Convert Activity Categories → Arts Queue
    # These are creative/expressive/social activities
    for category, topics in ACTIVITY_CATEGORIES.items():
        for topic in topics:
            arts_topics.append({
                "id": id_counter,
                "name": topic,
                "category": category,
                "sourceCategory": category
            })
            id_counter += 1

    # Convert Physical Activities → Physical Queue
    for category, topics in PHYSICAL_ACTIVITIES.items():
        for topic in topics:
            physical_topics.append({
                "id": id_counter,
                "name": topic,
                "category": category,
                "sourceCategory": category
            })
            id_counter += 1

    # Shuffle for initial randomization
    random.shuffle(arts_topics)
    random.shuffle(knowledge_topics)
    random.shuffle(physical_topics)

    # Build data structure
    data = {
        "masterLists": {
            "arts": arts_topics,
            "knowledge": knowledge_topics,
            "physical": physical_topics
        },
        "queues": {
            "arts": [t["id"] for t in arts_topics],
            "knowledge": [t["id"] for t in knowledge_topics],
            "physical": [t["id"] for t in physical_topics]
        },
        "completed": [],
        "development": [],
        "cycles": {
            "arts": 1,
            "knowledge": 1,
            "physical": 1
        },
        "version": "1.0"
    }

    # Write to file
    with open('docs/initial-data.json', 'w') as f:
        json.dump(data, f, indent=2)

    # Print statistics
    print(f"✅ Converted {len(arts_topics)} arts topics")
    print(f"✅ Converted {len(knowledge_topics)} knowledge topics")
    print(f"✅ Converted {len(physical_topics)} physical topics")
    print(f"📦 Total: {len(arts_topics) + len(knowledge_topics) + len(physical_topics)} topics")
    print(f"💾 Saved to docs/initial-data.json")

if __name__ == "__main__":
    convert_topics()
