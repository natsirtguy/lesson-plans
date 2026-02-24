# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Daily Lesson Plan Queue System for early childhood education (ages 2-3+ years). The system manages two independent FIFO queues of educational topics:

1. **Knowledge, Skills & Culture Queue** (316 topics - combined knowledge concepts, practical skills, and cultural/creative activities)
2. **Physical Activities Queue** (117 topics)

The system enables caregivers to select daily learning topics efficiently, ensuring balanced coverage across developmental domains while allowing flexibility to skip or flag topics for revision.

## Core Concepts

### Queue System Architecture
- Each queue operates as a circular buffer: when all items are completed, the queue automatically refills and begins a new cycle
- Items can be **selected** (marked complete and logged), **skipped** (moved to end of queue), or **flagged for development** (moved to Development Queue for revision/removal)
- The system is designed for collaborative use by multiple caregivers without requiring separate user identities

### Key Data Entities
- **Topic/Activity Item**: A single learning subject with name, description, category, queue assignment, and status
- **Queue State**: Current order and position for each queue
- **Completion Record**: Log of selected topics with date
- **Development Queue**: Holding area for topics needing revision
- **Master Lists**: Authoritative collections used to refill active queues when cycles complete

### Critical Requirements
- Mobile-first design (primary use case is on smartphones/tablets)
- Daily topic selection must take under 60 seconds
- Must support 2-3 concurrent users without conflicts
- Minimal/zero monthly cost ($0-10/month target)
- No authentication required (single household use)
- Real-time synchronization across devices (updates visible within 5 seconds)

## Data Structure

The repository currently contains:

- **topics.py**: Python dictionary definitions for the 433 initial topics organized by category
  - `KNOWLEDGE_AND_CULTURE_CATEGORIES`: 35 combined categories (19 knowledge + 16 activity/culture categories)
  - `PHYSICAL_ACTIVITIES`: 10 physical activity categories with topics
- **REQUIREMENTS.md**: Complete functional and non-functional requirements (Version 1.1)

### Topic Categories
Topics preserve their original source categories as metadata:
- Knowledge & Culture (Combined): Cross-Domain Foundational Concepts and Activities, Life Sciences, Physical Sciences, Earth & Space, Geography, Environmental Science, Individual/Social/Cultural/Economic/Linguistic Human Experience, Mathematical/Technological/Recreational/Creative Systems, Cognitive/Physical/Practical/Social-Emotional Skills, Visual/Performing/Literary Arts, Crafts, Digital Creation, Culinary Arts, Interpersonal/Group/Cultural Practices, Community Service, Communication, Teaching, Formal Learning, Games/Puzzles, Exploration, Cognitive Challenges, Research, Collecting, Household/Economic/Work/Maintenance/Planning/Safety/Transportation activities
- Physical: Individual/Team Sports, Individual Physical, Outdoor Adventure, Aquatic/Winter/Combat Sports, Mind-Body Activities, Performance Arts, Motor Skills

## Lesson Plan Backfill

### Current Status
- **Total topics**: 433
- **Lesson plans completed**: ~8 (as of Nov 2025)
- **Remaining**: ~425 lesson plans to generate

### Custom Subagents for Generation
Two specialized Claude Code subagents are available for lesson plan generation:

1. **knowledge-lesson-generator** (`.claude/agents/knowledge-lesson-generator.md`)
   - Generates Knowledge, Skills & Culture lesson plans (for the combined queue)
   - Output: `docs/lessons/knowledge/[topic-name].md`
   - Includes: vocabulary focus, learning activities, hands-on projects, age adaptations
   - Handles both knowledge topics and cultural/creative activities

2. **physical-lesson-generator** (`.claude/agents/physical-lesson-generator.md`)
   - Generates Physical Activities lesson plans
   - Output: `docs/lessons/physical/[activity-name].md`
   - Includes: equipment, space setup, warm-up/cool-down, safety considerations

Note: The former `arts-culture-lesson-generator` has been merged into `knowledge-lesson-generator` to reflect the combined queue structure.

### Usage Approach
**Model**: All subagents configured to use Haiku for cost-efficiency
**Token usage**: ~3,500-4,000 tokens per lesson plan (tested)
**Total estimated cost**: ~1.5M tokens for 425 lessons (within Claude Pro limits)

**Bulk generation process**:
1. Use Task tool with appropriate subagent type
2. Pass topic/activity name in prompt
3. Subagent generates comprehensive lesson plan following template
4. Review output quality periodically

**Note on Write operations**: Subagents may require approval for Write tool use depending on Claude Code settings. If auto-approval is not enabled, lesson plan content will need to be extracted from subagent output and saved manually.

### Educational Philosophy: Intellectual Rigor for Young Children
Lesson plans should be fun and hands-on, but **never dumbed down**. Young children — even toddlers — are capable of engaging with genuinely complex ideas. They won't understand everything, and that's fine. Early exposure to real concepts (real vocabulary, real mechanisms, real phenomena) primes children to see the world differently and builds a foundation for deeper understanding later.

**Guiding principles:**
- Use real scientific/technical terms alongside simple explanations. Say "photosynthesis" and then explain it — don't replace it with "how plants eat."
- Include actual content, not just themed play. A lesson on photosynthesis should teach that plants convert light into energy using chlorophyll, not just that "plants need sun."
- Trust that partial understanding has value. A 2-year-old who hears "carbon dioxide" during a plant lesson won't memorize the carbon cycle, but they're building neural pathways and comfort with scientific language.
- Activities should be genuinely engaging, not condescending. The goal is wonder and discovery, not simplified busywork dressed up in a topic's theme.
- Let complexity be the backdrop to play. A child painting leaves green is more meaningful when the caregiver mentions chlorophyll than when the activity is just "coloring."

### Intellectual Rigor Audit
Existing lesson plans are being audited against the above philosophy. Audit results are tracked in **`docs/lesson-audit.json`** — a flat JSON object keyed by relative file path (e.g. `knowledge/topic-name.md`). Do **not** read this file to check audit status; use the scripts below.

**Pre-selected audit batches**: 10 batches of 7 lessons each are pre-defined in `docs/audit-batches/`. Each file is a markdown checklist covering 70 of the 95 remaining unaudited lessons (as of 2026-02-24), mixing knowledge and physical topics:

| File | Lessons |
|------|---------|
| `docs/audit-batches/batch-01.md` | 5 knowledge, 2 physical |
| `docs/audit-batches/batch-02.md` | 5 knowledge, 2 physical |
| `docs/audit-batches/batch-03.md` | 5 knowledge, 2 physical |
| `docs/audit-batches/batch-04.md` | 5 knowledge, 2 physical |
| `docs/audit-batches/batch-05.md` | 5 knowledge, 2 physical |
| `docs/audit-batches/batch-06.md` | 5 knowledge, 2 physical |
| `docs/audit-batches/batch-07.md` | 4 knowledge, 3 physical |
| `docs/audit-batches/batch-08.md` | 5 knowledge, 2 physical |
| `docs/audit-batches/batch-09.md` | 4 knowledge, 3 physical |
| `docs/audit-batches/batch-10.md` | 5 knowledge, 2 physical |

To work through a batch, open the relevant file and audit the listed lessons one at a time. Mark `[x]` in the file as you go (optional), and always record each result with `record-audit-results.py` before moving on.

**Step 1 — Select lessons to audit**:
```bash
python select-audit-batch.py          # 25 random unaudited lessons (default)
python select-audit-batch.py 10       # custom batch size
python select-audit-batch.py --all    # list all remaining unaudited lessons
```
The script reads `docs/lesson-audit.json` and compares against lesson files on disk. It outputs file paths for unaudited lessons.

**Step 2 — Audit lessons one at a time**: Read a lesson, assess it against the rigor criteria, fix it if needed, then record the result before moving to the next lesson. Do not read all lessons in a batch upfront — that wastes context.

**Step 3 — Record each result immediately after auditing**:
```bash
# Lesson passes (already rigorous):
python record-audit-results.py docs/lessons/knowledge/topic.md PASS \
    "Uses real terminology: circadian rhythm, melatonin, REM sleep"

# Lesson fixed:
python record-audit-results.py docs/lessons/knowledge/topic.md "FAIL -> FIXED" \
    "No food chemistry, purely procedural" \
    "Added chemical reaction, emulsification, dissolve vocabulary"

# Lesson needs work but can't fix now:
python record-audit-results.py docs/lessons/physical/topic.md FAIL \
    "No anatomy or physiology content"
```

**Check status anytime**:
```bash
python record-audit-results.py --status              # summary stats
python record-audit-results.py --check <path>         # check specific lesson
```

**Verdict values**: `PASS` (already rigorous), `FAIL -> FIXED` (had issues, now fixed), `FAIL` (issues found but not fixable in this session)

Common patterns found in dumbed-down lessons:
- Vocabulary that uses only everyday words (e.g., "technology," "device") instead of real technical terms (e.g., "circuit," "sensor," "processor")
- Activities described as educational but containing no actual intellectual content — just themed play
- Missing key concepts that are central to the topic (e.g., a food chains lesson with no mention of energy transfer or decomposers)
- Process-only lessons that teach the feeling of learning without any real subject matter

### Lesson Plan Structure
All lesson plans follow age-appropriate educational design (ages 2-4+):
- Activity summaries with duration and materials
- Age-specific adaptations (2-3 years vs 3-4+ years)
- Common challenges with developmental explanations and solutions
- Safety considerations and parent/caregiver guidance
- Extension ideas for repeat engagement

## Implementation Considerations

### Technology Stack
- **Frontend**: Alpine.js 3.x SPA, Tailwind CSS, Marked.js (all via CDN)
- **Audio**: TinyMusic.js for song melody playback
- **Storage**: Browser localStorage for queue state persistence
- **Offline**: Service Worker (PWA installable on iOS/Android)
- **Hosting**: GitHub Pages serving static files from `/docs` folder (no build step)
- **Cost**: $0/month

### Website Architecture
The site is a single-page app at `docs/index.html`. There is no build step or static site generator — files in `/docs` are served directly by GitHub Pages.

**Critical: Two data sources must be kept in sync when modifying topics:**
- **`topics.py`**: Source of truth for topic definitions (used by verification scripts and lesson plan generation)
- **`docs/initial-data.json`**: The JSON file the website actually loads at runtime. Contains topic IDs, names, categories, and initial queue order. **If you only update `topics.py`, the website will not reflect the changes.**

**When adding a new topic (including when adding a new lesson plan for a topic that doesn't yet exist), you MUST update all three things:**
1. `topics.py` — add the topic name to the appropriate category list
2. `docs/initial-data.json` — add a new entry with a unique `id`, `name`, and `category` to the appropriate queue in `masterLists`
3. `docs/lessons/{queue}/{topic-name}.md` — the lesson plan file itself

If you only create the lesson plan file without registering the topic in both data sources, it will be invisible to search and inaccessible from the queue UI.

**How lesson plans are loaded at runtime:**
1. App converts topic name to filename (lowercase, spaces→hyphens, strip special chars)
2. Fetches `docs/lessons/{queue}/{filename}.md` via HTTP
3. Marked.js renders markdown to HTML client-side

### Data Migration
The initial data in topics.py (433 items) has been:
1. Parsed and transformed into `docs/initial-data.json`
2. Assigned to appropriate queues (Knowledge/Physical)
3. Loaded into master lists with randomized queue order

### Queue Operations
When implementing queue logic:
- **Select**: Remove from active queue → Add to completion log → Advance queue → Check if empty and refill if needed
- **Skip**: Remove from position → Append to end → Advance to next
- **Flag for Development**: Remove from active queue → Add to Development Queue with reason → Don't include in future refills until restored
- **Refill**: When last item selected → Restore all items from master list → Randomize order → Increment cycle counter

### Ideas Workflow (Simplified in v1.1)
When new ideas are submitted:
1. Add directly to the master list for specified queue
2. Add to beginning (next up position) of active queue by default
3. No separate "pending review" state needed

## User Workflows

### Primary Workflow: Daily Topic Selection
1. Open Daily Selection View (landing page)
2. Review current topic from each queue
3. For each queue: Select, Skip, or Flag as "Needs Work"
4. Complete selection of 1-3 topics in under 60 seconds

### Secondary Workflows
- Add new topic ideas on-the-go (mobile quick-add)
- Review and manage Development Queue (edit/delete/restore flagged topics)
- View completion history and learning patterns
- Manage master lists (bulk import/export, editing)
- Manual queue reset when needed

## Development Guidelines

### Performance Targets
- Queue displays load within 3 seconds on mobile connections
- System responds to user actions within 2 seconds
- Support up to 500 topics per queue
- Support up to 1000 completion log entries

### Data Integrity
- Prevent duplicate topics within same master list (warn before adding)
- Maintain referential integrity between completion records and topics
- Handle deleted topics gracefully in historical records (soft delete)
- Validate queue states contain only valid topic references

### UI/UX Priorities
1. Single-handed mobile operation
2. Touch targets minimum 44x44 pixels
3. Clear visual feedback for all actions
4. Contextual help/tooltips for advanced features
5. No training required for basic operations (select/skip)

## Testing Approach

When implementing features:
- Test queue refill logic (edge case: last item selected)
- Test concurrent access scenarios (multiple users selecting simultaneously)
- Test offline functionality if implemented
- Verify mobile responsiveness on various screen sizes
- Test data persistence and recovery
- Validate import/export functionality with actual topics.py data

## MCP Servers Available

This repository has two MCP servers configured:
- **serena** (@oraios/serena): Available for use
- **context7** (@upstash/context7): Available for use

Refer to their documentation for specific capabilities.
