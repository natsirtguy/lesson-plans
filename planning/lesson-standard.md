# Lesson Standard & Quarantine Workflow

This is the bar every knowledge lesson must clear to go live. It was distilled from
direct feedback on flagged lessons (2026-05 / 2026-07 / 2026-08) and the "intellectual
rigor for young children" philosophy in `CLAUDE.md`.

## The direction rule (the one that matters most)

**Topics come from the world, not from the activity shelf.**

There are two ways to end up with a lesson, and only one of them works:

- ❌ *Activity → knowledge.* Start with something toddlers already do — drawing, painting,
  fort-building, show-and-tell, playing with dolls — then bolt on some vocabulary to make it
  educational. This produces a lesson that is a craft session wearing a lab coat. Every
  lesson rejected in review so far failed this way.
- ✅ *Knowledge → activity.* Start with a genuinely interesting thing about the world.
  Then ask: what can a small child actually *do* that embodies this? Build the activity to
  serve the concept.

The test: **strip the activity out. Is there still a topic?** "Painting with various
materials" leaves nothing behind. "Pigments and where color comes from" survives on its
own — the paint-making is just how a 3-year-old touches it.

The corollary: a lesson does not exist to fill the session. If the best activity for a
great topic is small (three dots on paper, one hand held against a wall), that is fine.
A large, elaborate activity attached to nothing is worse than a small one attached to
something real.

## The standard

1. **One focused concept per lesson.** A lesson teaches a single, specific idea — "the
   phoneme," "germination," "cardinality," "the choke point" — not a grab-bag. If a topic
   sprawls across several ideas, **split it** into separate focused lessons.

2. **Knowledge over activity.** Teach a real *concept or phenomenon of the world*. Reject
   topics that are merely "do an activity," or that name something children acquire
   **automatically** through daily life (drawing, conversing, participating in a group,
   playing pretend). Such a thing may be the *vehicle* of a lesson but never its *subject*.

3. **Name the lesson after the concept, not the procedure.** "Buoyancy and why things
   float," not "Sink or float experiments." "Theory of mind," not "Show and tell." The
   title is the promise; make it a promise about the world.

4. **Real depth — never dumbed down.** Use the true term (phoneme, radicle, pareidolia,
   choke point, anthocyanin, altricial) and gesture at the advanced version even when
   simplified (Cantor's diagonal argument; false-belief tasks; structural color). Partial
   understanding has value; condescension does not.

5. **The activity must *be* the concept.** Open a seed to find the embryo. Sink the foil
   ball and float the foil boat. Grind turmeric and test four binders. Jam three stuffed
   animals in a doorway. If the activity would be unchanged with a different topic
   attached, it is generic themed play and does not count.

6. **Reach for the specific and surprising.** Given a broad area, take the sharpest angle
   in it. Not "art" but *what pigment is and where it comes from*. Not "forts" but *the
   choke point*. Not "drawing" but *why your brain puts a face in a cloud*. Wonder lives in
   the specific; the generic category is where lessons go to die.

7. **Use real references, and expect the caregiver to prepare.** Link to Wikipedia inline
   for the works, people, sites, and experiments named. Where the lesson turns on looking
   at something real — murals, castles, cave paintings, research footage — say plainly in
   the materials list that these should be **printed or pulled up ahead of time**, and
   build the activity around replicating or interrogating them. Real examples beat
   invention: replicate a style, copy a technique, rerun the actual experiment.

### Mechanical checklist (also required)
- Follows `docs/templates/knowledge-lesson-template.md` structure.
- All three sources updated in sync (see `CLAUDE.md`): `topics.py`,
  `docs/initial-data.json` (masterLists + queues), and the lesson `.md`.
- Filename = topic name lowercased, non-alphanumerics → hyphens. Avoid colons and
  apostrophes in topic names — `verify-lessons.py` and the app's JS derive filenames
  slightly differently and only agree on plain words, commas, and hyphens.
- `python3 verify-lessons.py` is green, and `python3 scripts/build-materials-index.py`
  has been rerun.

## Rewriting a "default activity" topic

When the backlog hands you a topic that is really just an activity, do not delete it and
do not paper over it. Ask what actually interesting thing sits underneath or nearby, and
promote *that*, retiring the old id as `resolved` in `quarantine/quarantine.json`. Worked
examples from batch 4:

| Activity topic | The real topic underneath |
| --- | --- |
| Show and tell | Theory of mind — what other people know, and don't |
| Drawing and scribbling | Pareidolia — the brain's face-detector firing on noise |
| Painting with materials | Pigments and binders — what color *is* |
| Building a blanket fort | Fortifications and choke points |
| Painting a group mural | Murals — 40,000 years of public art, and how to copy a style |
| Sink or float | Buoyancy (same lesson, honest name) |
| Sculpture with clay/playdough | Molds and casting — negative/positive, and one-to-many |
| Photography and picture-taking | The camera obscura — light travels in straight lines |
| Printmaking and stamping | Movable type — mirror reversal, and set once print many |
| Pottery and clay work | Why fire turns clay into stone — irreversibility |

One activity often contains several good topics (drawing yields both pigments *and*
pareidolia). Split them rather than cramming.

Two warning signs that a topic is really an activity in disguise:
- **The title contains a material or a tool** ("...with clay/playdough", "...and stamping").
  A concept title names a phenomenon, not a supply cupboard.
- **Two topics keep colliding.** 136 and 139 both drifted onto clay plasticity because
  neither was anchored to a concept. Give each a distinct idea and the collision resolves.

Expect the category to change when you do this properly. Four of the five "Visual Arts"
lessons in batch 5 turned out to be physics, materials science, and manufacturing once
they were named honestly. That is the direction rule working, not a filing error.

## Quarantine-first policy

**Default state for every topic is *quarantined*.** A topic is live only after its lesson
has been reviewed against the standard above and improved if needed. Presence on the site
is a stamp of approval, not the default.

- **Live (approved) knowledge topics** live in `topics.py` + `docs/initial-data.json`
  (masterLists/queues), with the lesson file in `docs/lessons/knowledge/`.
- **Quarantined topics** are listed in `quarantine/quarantine.json` (the review backlog,
  with id/name/category/reason), and their lesson files sit in
  `quarantine/lessons/knowledge/` — preserved, but not served and not reachable in the app.
- A full pre-quarantine snapshot is in `backups/initial-data.2026-07-14.json`.

### To promote a batch (the review loop)
Work batch by batch, usually one category at a time (see `quarantine/quarantine.json`):
1. Read the quarantined lesson(s). Judge against the standard.
2. Improve, rewrite, split, or replace as needed. Weak/duplicative topics may stay
   quarantined permanently or be merged.
3. Move the finished `.md` back to `docs/lessons/knowledge/` (`git mv` if it is a rename,
   so the history follows).
4. Add the topic to `topics.py` and `docs/initial-data.json` (masterLists + queues).
   New/split topics get a fresh unique id (ids 1091+ are free).
5. Mark the old id `resolved: true` in `quarantine/quarantine.json` with a reason saying
   what replaced it, and refresh the `counts` block.
6. Run `python3 verify-lessons.py` and `python3 scripts/build-materials-index.py`; commit
   the batch.

### Reviewing lessons flagged from the app
Flags arrive as a `development` array exported from the app — each entry has the topic id,
name, and the caregiver's `reason`. Sort them before working: some reasons are approvals
("good", "pretty good actually") and need no change at all; the rest name the specific
defect and usually the fix. Treat the reason as the spec.

## Status (2026-09-08, batches 4-5 plus one new lesson)

**Scope:** the knowledge queue only. Physical activities and songs are untouched (their
content is inherently activity/performance and outside this quality bar for now).

**Live knowledge lessons: 28** — the authoritative list is `topics.py` /
`docs/initial-data.json` (masterLists.knowledge). How they got there:
- Original 6: sensory-system idiosyncrasies (247), seeds/germination + decomposition
  (1076/1077, split from "Community garden"), counting/cardinality/infinity (1078),
  phonemes (1079, replaced 152), conversation across cultures (1080, replaced 183).
- Batch 2 (Cross-Domain Foundational Activities, 15 reviewed): 10 promoted in place; 4
  grab-bag titles replaced by concept names — mirror neurons (1081←119), attachment
  biology (1082←126), symbolic thinking (1083←128), entrainment (1084←131); 1 retired as
  duplicative (125).
- Batch 3 (Visual Arts, 8 reviewed): 7 promoted with concept-first summaries; 1 retired as
  duplicative (140).
- Batch 4 (app flags, 12 reviewed): 5 confirmed good and left alone (141, 1076, 1077,
  1078, 1079). 6 replaced under concept names — theory of mind (1085←129), pareidolia
  (1086←134), pigments (1087←135), fortifications (1088←133), murals (1089←132), buoyancy
  (1090←123). 1 kept but rebuilt: attachment (1082), whose framing was sound but whose
  activity was doll play; it now runs the secure-base radius, social-referencing, and
  co-regulation experiments on the child directly.
- Batch 5 (the four batch-3 leftovers, re-reviewed against the direction rule): all four
  failed it — concept-first *summaries* over craft-session activities, with 136 and 139
  duplicating each other on clay. Replaced by molds and casting (1091←136), camera obscura
  (1092←137), movable type (1093←138), and why fire turns clay into stone (1094←139).
  Their categories moved with them, out of Visual Arts into physical sciences and
  technology.
- New lesson, written to request rather than promoted from quarantine: keratin and why
  hair is a rope (1095, Life Sciences). Hierarchical twisting — a keratin chain coils into
  an alpha helix, two helices into a coiled coil, and five more levels of the same trick
  produce a visible hair. The activity plies sewing thread up the same ladder and
  break-tests each level, so the strength that appears out of nothing *is* the concept.
  Cuticle scales/felting and disulfide bonds/perms are kept subordinate as extensions.

**Quarantined:** 294 knowledge topics await review (`quarantine/quarantine.json`;
`resolved: true` entries are review decisions already made — replaced or merged).

### Pending follow-ups
- **228 Workshop and lesson participation** → optional: reframe the good *social-learning /
  collective intelligence* content as a pure knowledge topic.
- **239 Math games** → further math splits beyond 1078 and 124 (patterns as proto-algebra
  is live via the bead-necklace lesson; still open: shapes/symmetry, measurement).
- **Abscission / why leaves change color** → currently a supporting idea inside 130
  (nature display) and 1087 (pigments); wonderful enough to deserve its own lesson.
- **Material dictates the pose** → dropped from the 136 rewrite to keep it focused, but
  it is a strong topic on its own: marble is weak in tension so Roman marble copies of
  Greek bronzes need tree-stump struts under the limbs, while bronze can rear a horse on
  two legs. Structural forces (load-bearing, tension, compression) also lost their home
  when the blanket-fort lesson became fortifications, so this would cover both.
- **The remaining Cross-Domain Foundational Activities** (120, 121, 122, 124, 127, 130)
  were promoted in batch 2 as already-refocused lessons. They have not been re-read since
  the direction rule was written down; several of their titles still name procedures
  ("Making a picture diary or journal", "Creating a nature display from a walk").
