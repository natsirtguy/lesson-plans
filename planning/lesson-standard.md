# Lesson Standard & Quarantine Workflow

This is the bar every knowledge lesson must clear to go live. It was distilled from
direct feedback on flagged lessons (2026-05 / 2026-07) and the "intellectual rigor for
young children" philosophy in `CLAUDE.md`.

## The standard (what makes a lesson good, not junk)

1. **One focused concept per lesson.** A lesson teaches a single, specific idea — "the
   phoneme," "germination," "cardinality" — not a grab-bag. If a topic sprawls across
   several ideas (e.g. seeds *and* decomposition, or "math games"), **split it** into
   separate focused lessons.

2. **Knowledge over activity.** Teach a real *concept or phenomenon of the world* — a
   topic of human understanding. Reject topics that are merely "do an activity" or that
   name a skill children acquire **automatically** through daily life (conversing,
   participating in a group). Such a topic only qualifies if it is reframed around a
   genuine concept (e.g. "conversation practice" → *the anthropology of how conversation
   norms differ across cultures*).

3. **Real depth — never dumbed down.** Name the real idea and reach higher than expected.
   Use the true term (phoneme, radicle, sensory adaptation, one-to-one correspondence) and
   gesture at the advanced version even when simplified (Cantor's diagonal argument;
   cross-linguistic phonology). Partial understanding has value; condescension does not.

4. **The activity must *be* the concept.** The hands-on activity should directly
   demonstrate that specific idea — open a seed to find the embryo, run the three-bowls
   temperature illusion — not generic themed play ("do some gardening," "explore a bin").
   Activity and concept must match.

5. **Favor wonder and the counterintuitive.** Prefer the surprising, the specifically
   *human*, the "you can fool your own brain" angle. That is what makes rigor delightful.

### Mechanical checklist (also required)
- Follows `docs/templates/knowledge-lesson-template.md` structure.
- All three sources updated in sync (see `CLAUDE.md`): `topics.py`,
  `docs/initial-data.json` (masterLists + queues), and the lesson `.md`.
- Filename = topic name lowercased, non-alphanumerics → hyphens (see `verify-lessons.py`).
- `python3 verify-lessons.py` is green.

## Quarantine-first policy

**Default state for every topic is *quarantined*.** A topic is live only after its lesson
has been reviewed against the standard above and improved if needed. Presence on the site
is a stamp of approval, not the default.

- **Live (approved) knowledge topics** live in `topics.py` +
  `docs/initial-data.json` (masterLists/queues), with the lesson file in
  `docs/lessons/knowledge/`.
- **Quarantined topics** are listed in `quarantine/quarantine.json` (the review backlog,
  with id/name/category/reason), and their lesson files sit in
  `quarantine/lessons/knowledge/` — preserved, but not served and not reachable in the app.
- A full pre-quarantine snapshot is in `backups/initial-data.2026-07-14.json`.

### To promote a batch (the review loop)
Work batch by batch, usually one category at a time (see `quarantine/quarantine.json`):
1. Read the quarantined lesson(s). Judge against the standard.
2. Improve, rewrite, split, or replace as needed. Weak/duplicative topics may stay
   quarantined permanently or be merged.
3. Move the finished `.md` back to `docs/lessons/knowledge/`.
4. Add the topic to `topics.py` and `docs/initial-data.json` (masterLists + queues).
   New/split topics get a fresh unique id (ids 1076+ are in use).
5. Remove it from `quarantine/quarantine.json`.
6. Run `python3 verify-lessons.py`; commit the batch.

## Status (2026-07-14)

**Scope:** the knowledge queue only. Physical activities and songs are untouched (their
content is inherently activity/performance and outside this quality bar for now).

**Live knowledge lessons (4):**
- Sensory exploration activities (247) — refocused onto sensory-system idiosyncrasies
  (adaptation, two-point discrimination, the three-bowls illusion).
- Seeds and germination (1076) — split from "Community garden"; open-a-seed activity.
- Decomposition and compost (1077) — split from "Community garden"; rot-jar activity.
- Counting, cardinality, and infinity (1078) — replaces the first slice of "Math games";
  one-to-one correspondence → a taste of Cantor's infinities.

**Quarantined:** 320 knowledge topics await review (`quarantine/quarantine.json`).

### Pending replacements for the originally-flagged topics
- **152 Reading and book exploration** → write a Linguistics lesson on *the phoneme* and
  how sound inventories differ across languages (minimal pairs; sounds English lacks).
- **183 Conversation and dialogue practice** → write an Anthropology/pragmatics lesson on
  *how conversation norms differ across cultures* (turn-taking gaps, greetings, personal
  space, high/low-context).
- **228 Workshop and lesson participation** → optional: reframe the good *social-learning /
  collective intelligence* content as a pure knowledge topic.
- **239 Math games** → further math splits beyond 1078 (e.g. shapes/symmetry, measurement,
  patterns as proto-algebra).
