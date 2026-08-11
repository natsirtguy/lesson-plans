# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

**Mentot** — a daily lesson plan queue for a young child (ages 2-4+). The app shows one
topic from each queue (knowledge, physical, songs), and the caregiver selects it, skips it,
or flags it as "needs work." Most of the value in this repo is the **lesson plans**
themselves; the app is a thin static SPA for serving them.

Full behavioural spec: `REQUIREMENTS.md`. Stack, layout, and local-dev instructions:
`README.md`. Don't duplicate either of those here — this file is for the things you would
otherwise get wrong.

## The two rules that break things

### 1. Three sources must be updated together

Adding, renaming, or removing a topic touches **three** places. Miss one and the topic is
invisible to search, unreachable from the queue, or a 404 when opened:

1. `topics.py` — topic name in the right category list (used by `verify-lessons.py`)
2. `docs/initial-data.json` — an entry in `masterLists.<queue>` (unique `id`, `name`,
   `category`) **and** the id in `queues.<queue>`. This is the file the site actually
   loads at runtime.
3. `docs/lessons/<queue>/<filename>.md` — the lesson itself

Then rerun both scripts:

```bash
python3 verify-lessons.py                  # topics.py <-> lesson files must match exactly
python3 scripts/build-materials-index.py   # rebuilds docs/materials-index.json for search
```

### 2. Filenames are derived, and derived twice

The app converts a topic name to a filename in JS at runtime; `verify-lessons.py` does the
same in Python. The two implementations **disagree on punctuation** — Python hyphenates
only `( ) , / whitespace`, while the JS strips all non-word characters first. They agree on
plain words, commas, and hyphens, so keep topic names to those. A colon or apostrophe in a
topic name will pass verification and 404 in the browser.

## Lesson plans

### Templates
- Knowledge: `docs/templates/knowledge-lesson-template.md`
- Physical: `docs/templates/physical-lesson-template.md`
- Songs: `docs/templates/song-lesson-template.md`

Follow the corresponding template's structure and section ordering.

### Educational philosophy: intellectual rigor for young children

Lesson plans should be fun and hands-on, but **never dumbed down**. Young children — even
toddlers — are capable of engaging with genuinely complex ideas. They won't understand
everything, and that's fine. Early exposure to real concepts (real vocabulary, real
mechanisms, real phenomena) primes children to see the world differently and builds a
foundation for deeper understanding later.

- Use real scientific and technical terms alongside simple explanations. Say
  "photosynthesis" and then explain it — don't replace it with "how plants eat."
- Include actual content, not just themed play.
- Trust that partial understanding has value. A 2-year-old who hears "carbon dioxide"
  during a plant lesson isn't memorizing the carbon cycle, but is building comfort with
  scientific language.
- Let complexity be the backdrop to play. A child painting leaves green is doing something
  more interesting when the caregiver mentions chlorophyll.

**The direction rule.** Topics come from the world, not from the activity shelf. Never
start with something toddlers already do (drawing, painting, fort-building, show-and-tell,
pretend play) and bolt a knowledge angle onto it — that produces a craft session in a lab
coat, and it is how every rejected lesson so far went wrong. Start with a genuinely
interesting phenomenon, then find the activity that *embodies* it. Test: strip the activity
out; is there still a topic? "Painting with various materials" leaves nothing. "Pigments
and where color comes from" survives on its own.

Name lessons after the concept rather than the procedure, take the sharpest specific angle
in a broad area, and link real references (Wikipedia inline; printed examples in the
materials list) so activities can replicate real work instead of inventing filler.

The full bar, the rewrite recipe for "default activity" topics, and worked examples are in
**`planning/lesson-standard.md`** — read it before writing or reviewing any lesson.

### Quarantine-first policy

**The default state for every knowledge topic is *quarantined*.** A topic is live only
after its lesson has been reviewed against `planning/lesson-standard.md` and improved if
needed — presence on the site is a stamp of approval, not the default. Do **not** re-add
quarantined topics wholesale or "restore" them to make counts match; promote them one
reviewed batch at a time.

- **Live/approved**: in `topics.py` + `docs/initial-data.json`, lesson in
  `docs/lessons/knowledge/`.
- **Quarantined**: listed in `quarantine/quarantine.json` (the review backlog), lessons
  preserved under `quarantine/lessons/knowledge/` (not served).
- Full pre-quarantine snapshot: `backups/initial-data.2026-07-14.json`.

Scope is the knowledge queue only — physical activities and songs are untouched.

### Reviewing flags from the app

Caregiver feedback arrives as a JSON export whose `development` array holds the flagged
topics with a free-text `reason`. Some reasons are approvals and need no change; the rest
name the defect and usually the fix. Treat the reason as the spec, and record the outcome
of every flag in `quarantine/quarantine.json` and the status section of
`planning/lesson-standard.md`.
