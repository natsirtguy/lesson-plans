# CLAUDE.md — Adaptive Tutor

Guidance for Claude Code when working inside `tutor/`. This directory is a **separate
product** from the toddler lesson-plan queue that occupies the rest of this repository.
Nothing in `tutor/` is served by GitHub Pages, and nothing here reads `topics.py` or
`docs/initial-data.json`. If you are editing the toddler site, the root `CLAUDE.md`
applies instead.

## What this is

A personal adaptive-learning app. The user names a subject; the app decomposes it into a
concept DAG, quizzes adaptively to estimate per-node mastery, reports strengths and gaps,
and generates a prerequisite-respecting lesson plan plus a spaced-study schedule. A
persistent "ask anything" box turns any question into a lesson that folds back into the
knowledge model.

## Layout

```
tutor/
  backend/
    app/
      main.py            FastAPI app factory, lifespan, SSE wiring
      config.py          pydantic-settings; all config via .env
      db.py              async engine/session, Base
      models/            SQLAlchemy 2.0 ORM (Mapped[...] style)
      schemas/           Pydantic v2 API schemas (never reused as ORM)
      mastery/           PURE functions: elo, propagation, selection, decay, reconcile
      graphs/            concept-graph ops: changeset validation + application
      scheduling/        fsrs.py (item intervals), planner.py (session planning)
      llm/               typed adapter boundary: base.py, anthropic.py, fake.py, prompts.py
      repositories/      persistence only; own the SQL
      services/          all business logic
      routers/           parse/validate/delegate; no logic
    alembic/             migrations
    tests/               pytest; zero network calls
  frontend/              React + Vite + TS PWA
  docs/                  design notes worth keeping
```

## Hard rules

1. **No business logic in routers.** Routers validate input, call a service, shape a
   response. If a router contains a conditional about mastery, scheduling, or graph
   integrity, it belongs in a service.
2. **Services never import the Anthropic SDK.** Every model call goes through
   `app.llm.base.LLMAdapter`. Tests inject `FakeLLMAdapter`; the suite makes **zero**
   network calls. If you add an LLM capability, add it to the Protocol and to *both*
   implementations.
3. **`mastery/` is pure.** No DB, no I/O, no clock reads except values passed in as
   arguments. Everything takes state and returns new state. This is what makes the model
   testable against a synthetic learner.
4. **Structured generation uses tool-use with a Pydantic v2 schema**, never
   "please return JSON". Validate, and retry exactly once on validation failure.
5. **Type hints on everything**, including private helpers and test helpers.
   `mypy --strict` must stay clean.
6. **reST docstrings, no type information in them.** The annotations are the types;
   repeating them in `:type x:` lines is redundant. Document meaning, units, and ranges.
7. **Nothing about the graph commits without per-operation approval.** The refine
   endpoint proposes; the changeset endpoint commits only the ops marked accepted.
8. **Soft-delete concepts, never hard-delete.** Mastery history survives removal so
   re-adding a concept restores it.

## Domain invariants

- **Edge direction:** an edge is stored as `(prereq_id -> node_id)` and means *prereq must
  be learned before node*. `ancestors(n)` are prerequisites, `descendants(n)` are things
  that depend on n. Getting this backwards silently inverts propagation, so any new graph
  code should be tested against `tests/test_propagation.py`'s fixture.
- **The graph is a DAG.** Enforced at changeset validation time, not just at generation.
- **Tier monotonicity:** a prerequisite edge may not point from a higher tier to a lower
  tier. Tier 1 is foundational, tier 5 is advanced.
- **`graph_version`** is monotonic per subject and bumps on every committed changeset.
  Changesets are an append-only log; never rewrite one.
- **Coverage is honest**: it is a function of estimated mastery over all live nodes, never
  of lessons completed. Do not "improve" it by counting completions.

## Mastery reconciliation (the easy-to-break part)

When the graph changes, mastery must be carried across explicitly. These rules are
implemented in `app/mastery/reconcile.py` and each has a test:

| Operation | Mastery | Confidence |
| --- | --- | --- |
| `split_node` | each child inherits parent's mastery | parent's × `SPLIT_CONFIDENCE_FACTOR` (0.5) |
| `merge_nodes` | confidence-weighted mean of inputs | **minimum** of inputs, not the mean |
| `add_node` | decayed mean of prerequisites' mastery (never 0) | low (`SEEDED_CONFIDENCE`) |
| `remove_node` | row kept, soft-deleted | unchanged, restored on re-add |
| edge changes | unchanged directly | posterior recomputed over affected subgraph |

Seeding a new node at zero mastery is a bug, not a conservative default: it fabricates a
weakness and burns diagnostic questions confirming the learner doesn't know something
their prerequisites imply they probably do.

Two consequences that are easy to undo by accident, both with a test guarding them:

- **Reconciled nodes are exempt from `smooth_posterior`.** A split child inherits its
  parent's estimate *by rule*; capping it against its (weak) prerequisites silently
  undoes the rule and destroys exactly the history the split was meant to preserve.
  `ChangesetService` passes `protected=` for this reason.
- **An `add_node` that resolves to a soft-deleted row keeps the stored mastery, not the
  seed.** Overwriting it with a fresh prerequisite-derived seed is the data loss that
  re-adding is supposed to avoid. Reviving does *not* restore the concept's old edges —
  the operation's `prereq_ids` are honoured as written, so re-adding a tier-3+ concept
  with no prerequisites is correctly rejected as an orphan.

## Where the mastery model departs from the original spec

Both of these were found by the synthetic-learner test, which failed loudly with the
literal reading. Do not "fix" them back.

1. **Propagation carries a bound, not only a decayed delta.** Nudging a neighbour by
   a share of the delta is too weak to travel: a learner who demonstrates tier-4
   competence still read as a beginner at tier 1, because 30 questions cannot touch
   100 nodes. So success also imposes a *floor* on prerequisites and failure a
   *ceiling* on dependents — the constraint that a concept cannot be much better
   known than what it is built on, loosening by `prereq_bound_slack` per hop.
2. **Item selection weights by expected reach, not by unblocking power.** Weighting
   purely by "how many nodes does this unblock" sends the selector into the
   foundations and keeps it there, because success at a root propagates nowhere —
   a root has no prerequisites. The reach term is therefore
   `P(correct) × weighted-prerequisites + P(wrong) × weighted-dependents`; unblocking
   power is the failure half of that expectation rather than the whole of it. This is
   what makes the search bisect the DAG instead of sweeping it.

A third addition has no counterpart in the spec: `refresh_priors` re-derives the
*prior* of weakly-evidenced nodes from their prerequisites and from how the learner
has fared at that difficulty tier. It is not evidence propagation — confidence is
never raised by it — but without it every untested concept sits at the seed it was
given before anything was known about the learner.

**Tunables are calibrated, not guessed.** The defaults in `mastery/state.py` were
swept against the synthetic learner across four learner profiles, seven answer seeds,
and four graph shapes. Changing one means re-running
`tests/test_mastery_synthetic.py` and expecting to be told if it made things worse.

**The same defaults must appear in `config.py`.** Services build their params through
`MasteryParams.from_settings`, so a value that drifts in config silently de-calibrates
the running app while every assertion against `DEFAULT_PARAMS` keeps passing. That drift
happened once already. `test_configured_defaults_match_the_calibrated_ones` is the guard;
if you add a tunable to `Settings`, wire it through `from_settings` or the guard will
not cover it.

## Plan sequencing

`graphs/sequencer.py` is pure and holds the ordering invariant: a unit is only ever
emitted from the **ready set** — concepts whose every prerequisite is already mastered or
already scheduled earlier in the same plan — and among those, the highest-priority one
wins. Prerequisite-respecting order is therefore a loop invariant, not something checked
afterwards. `tests/test_sequencer.py` asserts it over three graph shapes and
`tests/test_plan.py` asserts it again over a plan built from a generated graph.

Priority is `mastery.coverage.priority`, shared with the report on purpose: the concepts
the report calls out as worth attacking are exactly the ones the plan front-loads.

**Unit prose is written lazily.** A plan is created with a deterministic placeholder title
and objective and costs zero model calls; the `UnitBrief` call, the exit-check items, and
the lesson row all happen on first serve of that unit. Generating a hundred briefs up
front would blow the "subject to plan in under five minutes" criterion for content the
learner will not see for weeks, pitched against a mastery estimate that will have moved.

Every graded answer — diagnostic, exit check, or review — goes through
`services/mastery_service.MasteryUpdater`. Do not re-implement update-then-propagate-then-
refresh anywhere else; one belief about the learner, one code path that writes it.

## Two scheduling layers — do not conflate them

- **Layer 1, FSRS (`scheduling/fsrs.py`)** decides *when an item is due*. Grades come from
  the LLM rubric score via `grade_from_score`, never from self-report. A lapse enters
  relearning steps; an interval is never reset to zero.
- **Layer 2, the session planner (`scheduling/planner.py`)** decides *when the user sits
  down and what happens in that sitting*. Session shape is fixed: due retrieval first,
  then new material, then an exit check. Retrieval before instruction, always.

A card is keyed on **node**, not on a specific generated item: items are LLM-generated and
disposable, so the scheduling state lives on the concept and each retrieval draws a fresh
item for it. This is a deliberate deviation from card-per-item FSRS; it keeps intervals
stable when item content is regenerated.

## Conventions

- Python 3.12, async everywhere. `async def` all the way down; no sync DB calls.
- SQLite for dev, but **keep the schema Postgres-compatible**: no SQLite-only types, use
  `String` with explicit lengths, store JSON via `sa.JSON`, timestamps as timezone-aware.
- IDs are UUID4 strings (`str`), generated in Python, so tests are deterministic when seeded
  and inserts don't need a round-trip.
- Cache LLM output in the DB keyed by `(node, difficulty, level)`. Regenerating identical
  content costs money for no gain.
- Frontend keeps deps minimal and hand-rolls the graph layout; no chart or graph library.

## Commands

```
make dev      # backend on :8000 + frontend on :5173
make check    # ruff + mypy --strict + pytest   <- must pass before every commit
make test
make migrate  # alembic upgrade head
docker compose up
```
