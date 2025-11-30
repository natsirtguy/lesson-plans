# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Daily Lesson Plan Queue System for early childhood education (ages 2-3+ years). The system manages three independent FIFO queues of educational topics:

1. **Arts & Culture Queue** (68 topics)
2. **Knowledge & Skills Queue** (248 topics)
3. **Physical Activities Queue** (117 topics)

The system enables caregivers to select daily learning topics efficiently, ensuring balanced coverage across developmental domains while allowing flexibility to skip or flag topics for revision.

## Core Concepts

### Queue System Architecture
- Each queue operates as a circular buffer: when all items are completed, the queue automatically refills and begins a new cycle
- Items can be **selected** (marked complete and logged), **skipped** (moved to end of queue), or **flagged for development** (moved to Development Queue for revision/removal)
- The system is designed for collaborative use by multiple caregivers without requiring separate user identities

### Key Data Entities
- **Topic/Activity Item**: A single learning subject with name, description, category, queue assignment, and status
- **Queue State**: Current order and position for each of the three queues
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
  - `KNOWLEDGE_CATEGORIES`: 19 knowledge categories with topics
  - `ACTIVITY_CATEGORIES`: 16 activity categories with topics
  - `PHYSICAL_ACTIVITIES`: 10 physical activity categories with topics
- **REQUIREMENTS.md**: Complete functional and non-functional requirements (Version 1.1)

### Topic Categories
Topics preserve their original source categories as metadata:
- Knowledge: Cross-Domain Foundational, Life Sciences, Physical Sciences, Earth & Space, Geography, Environmental Science, Individual/Social/Cultural/Economic/Linguistic Human Experience, Mathematical/Technological/Recreational/Creative Systems, Cognitive/Physical/Practical/Social-Emotional Skills
- Activities: Cross-Domain Foundational, Visual/Performing/Literary Arts, Crafts, Digital Creation, Culinary Arts, Interpersonal/Group/Cultural Practices, Community Service, Communication, Teaching, Formal Learning, Games/Puzzles, Exploration, Cognitive Challenges, Research, Collecting, Household/Economic/Work/Maintenance/Planning/Safety/Transportation activities
- Physical: Individual/Team Sports, Individual Physical, Outdoor Adventure, Aquatic/Winter/Combat Sports, Mind-Body Activities, Performance Arts, Motor Skills

## Lesson Plan Backfill

### Current Status
- **Total topics**: 433
- **Lesson plans completed**: ~8 (as of Nov 2025)
- **Remaining**: ~425 lesson plans to generate

### Custom Subagents for Generation
Three specialized Claude Code subagents have been created for efficient lesson plan generation:

1. **knowledge-lesson-generator** (`.claude/agents/knowledge-lesson-generator.md`)
   - Generates Knowledge & Skills lesson plans
   - Output: `docs/lessons/knowledge/[topic-name].md`
   - Includes: vocabulary focus, learning song, hands-on activities, age adaptations

2. **arts-culture-lesson-generator** (`.claude/agents/arts-culture-lesson-generator.md`)
   - Generates Arts & Culture lesson plans
   - Output: `docs/lessons/arts/[activity-name].md`
   - Includes: materials, step-by-step setup, session structure, cultural context

3. **physical-lesson-generator** (`.claude/agents/physical-lesson-generator.md`)
   - Generates Physical Activities lesson plans
   - Output: `docs/lessons/physical/[activity-name].md`
   - Includes: equipment, space setup, warm-up/cool-down, safety considerations

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

### Lesson Plan Structure
All lesson plans follow age-appropriate educational design (ages 2-4+):
- Activity summaries with duration and materials
- Age-specific adaptations (2-3 years vs 3-4+ years)
- Common challenges with developmental explanations and solutions
- Safety considerations and parent/caregiver guidance
- Extension ideas for repeat engagement

## Implementation Considerations

### Technology Stack (To Be Determined)
The requirements document is platform-agnostic. When implementing, consider:
- Mobile-first responsive web application (likely approach given cost constraints)
- Real-time database with offline support (e.g., Firebase, Supabase, or similar)
- Simple state management for queue operations
- Import/export functionality for CSV/JSON backup

### Data Migration
The initial data in topics.py (433 items) needs to be:
1. Parsed and transformed into the target data model
2. Assigned to appropriate queues (Arts/Knowledge/Physical)
3. Loaded into master lists
4. Used to initialize active queues with randomized order

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
