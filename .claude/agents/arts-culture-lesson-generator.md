---
name: arts-culture-lesson-generator
description: DEPRECATED - Arts & Culture topics have been merged into the Knowledge, Skills & Culture queue. Use knowledge-lesson-generator instead.
tools: Read, Write, Glob, Grep
model: haiku
---

# ⚠️ DEPRECATED: Arts & Culture Lesson Generator

**This agent has been deprecated as of January 2026.**

## What Changed?

The lesson plan queue system has been updated to combine Arts & Culture topics with Knowledge & Skills into a single **Knowledge, Skills & Culture** queue. This provides better integration between cognitive learning and creative/cultural activities.

## What to Use Instead

**Use the `knowledge-lesson-generator` agent** for all topics that were previously in the Arts & Culture queue.

The knowledge-lesson-generator now handles:
- Knowledge concepts (e.g., "Weather and seasons", "Emotions and feelings")
- Practical skills (e.g., "Food preparation and cooking", "Personal hygiene")
- Creative activities (e.g., "Drawing, sketching, and scribbling", "Music and singing")
- Cultural activities (e.g., "Holiday celebrations", "Cultural dance and music")

## How to Use the Knowledge Lesson Generator

Simply invoke the `knowledge-lesson-generator` agent with your topic name:

```
Task: Generate a lesson plan for "Drawing, sketching, and scribbling"
Agent: knowledge-lesson-generator
```

All lesson plans will be saved to `docs/lessons/knowledge/` regardless of whether they're knowledge concepts or cultural/creative activities.

---

**Note**: This deprecation notice is kept for backward compatibility. All future lesson plan generation should use `knowledge-lesson-generator`.
