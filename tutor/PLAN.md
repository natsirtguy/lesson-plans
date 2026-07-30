# Implementation plan

Short version of what gets built, in what order, and the decisions I made without asking.

## Decisions taken without asking

| Decision | Choice | Why |
| --- | --- | --- |
| Where the app lives | `tutor/`, a sibling of the existing toddler lesson-plan site | The repo root is already a shipped product served from `/docs` by GitHub Pages. Dropping a FastAPI app at the root would collide with it. |
| FSRS card granularity | one card per **concept node**, not per generated item | Items are LLM-generated and disposable. Card-per-item would reset scheduling every time an item is regenerated. Each retrieval draws a fresh item for the concept. |
| Grade derivation | rubric score → 4-point scale at fixed cut points (<0.6 again, <0.75 hard, <0.9 good, else easy) | Spec says grades come from the rubric, not self-report. Cut points are config, not magic numbers. |
| Styling | hand-rolled CSS design tokens, no Tailwind | Spec asks for a calm, deliberate look and explicitly not default-Tailwind scaffolding. A small token system gets there with less markup noise. |
| Graph layout | hand-written layered DAG in SVG (tier = layer), no graph library | Needs to be readable on a phone and work offline; d3/cytoscape are large and fight touch handling. |
| Auth | none | Single-user personal app, same as the rest of this repo. |
| Postgres | schema kept Postgres-compatible, dev runs SQLite | Spec asks for exactly this. `docker compose` ships a Postgres profile. |

## API changes from the spec

The spec's surface is kept verbatim. Additions, all additive:

- `GET /subjects` — list subjects; the UI needs a landing page.
- `GET /subjects/{id}` — subject metadata + cadence + graph version, without pulling the full graph.
- `GET /lessons/{id}` — fetch already-generated lesson markdown. `POST /ask` and plan units
  stream over SSE, and streamed responses can't be cached by a service worker; a plain GET of
  the persisted markdown is what makes offline review work.
- `POST /subjects/{id}/reviews/answer` — grade a retrieval that came from the review queue
  rather than from a diagnostic or an exit check. Without it, FSRS has no way to receive a
  grade for a plain review touch. Scoped under the subject (the spec wrote `/reviews/answer`)
  because the handler has to verify the item belongs to the subject being reviewed.
- `GET /subjects/{id}/reviews` and `GET /subjects/{id}/reviews/next` — the due queue, and the
  question drawn for the top of it.
- `GET /subjects/{id}/calibration` — retrieval-success stats and the widen/tighten advice.
  Folded into the report response too, but useful alone.
- `GET /subjects/{id}/plan` and `GET /plan/{id}` — read the current plan without regenerating it.
  `POST /subjects/{id}/plan` supersedes the existing plan, so it can't double as a read.
- `POST /lessons/{id}/stream` — SSE stream that fills a lesson row's prose. POST rather than
  GET because it persists what it generates, which is what makes the subsequent
  `GET /lessons/{id}` work offline.
- `POST /plan/{id}/units` — accept an ask-anything plan offer by scheduling a concept.
  Without it the offer is decoration.

`POST /ask` is scoped under its subject as **`POST /subjects/{id}/ask`**: a question is
classified against one subject's graph and its answer is stored against that subject, so
the subject is not an optional detail of the body.

One rename from the spec's surface, not an addition:

- `POST /lessons/{id}/complete` → **`POST /plan/units/{unit_id}/complete`**. The thing that
  gets completed is a plan *unit*; a `Lesson` is cached prose keyed on
  `(node, difficulty, level)` and is deliberately shareable — the same lesson row can back a
  plan unit and an ask-anything answer. Keeping the spec's path would have meant a `{id}`
  that is a unit id on an endpoint named for lessons. `GET /lessons/{id}` still fetches the
  prose itself.

## Order of work

1. **Schema + harness.** ORM models for subjects, nodes, edges, mastery, changesets +
   ops, diagnostic sessions, items, responses, plans + units, lessons, review cards,
   study sessions, suggestions. One Alembic migration. `LLMAdapter` Protocol with the
   Anthropic implementation and a deterministic fake. pytest fixtures giving an async
   session on an in-memory SQLite DB and an `httpx.AsyncClient` wired to the fake adapter.
2. **`mastery/`.** Pure functions and their tests, including the synthetic-learner
   recovery test. No DB, no clock. Proven before anything consumes it.
3. **Graph generation.** Structured LLM call → validated DAG → persisted nodes/edges with
   seeded mastery. `GET /subjects/{id}/graph`.
4. **Changesets.** The nine operations, the four validation rules, mastery reconciliation,
   append-only versioned log, proactive suggestion detection. Tested before the diagnostic
   exists because everything downstream trusts graph integrity.
5. **Diagnostic.** Selection → item generation (cached) → grading → propagated update →
   stopping rule.
6. **Report + plan.** Coverage, strengths/weaknesses, blocking tiers, then a topological
   sequencing weighted by weakness × unblocking power, units with objective/explanation/
   worked examples/practice/exit check.
7. **Ask-anything.** Classification against the graph, streamed lesson, satellite node
   handling for off-subject queries, plan-insertion offer.
8. **FSRS + decay.** FSRS-4.5 with published default weights, relearning steps, due queue
   under a daily cap.
9. **Session planner.** Session shape, interleaving policy, expanding schedule for new
   nodes, cap smoothing, calibration, rolling two-week schedule, deadline mode.
10. **Frontend.** Graph viewer, diagnostic runner, report, plan/lesson reader, changeset
    diff UI, schedule view, Cmd+K ask palette, service worker.

    Two decisions taken while building it. The lesson renderer (marked + KaTeX +
    highlight.js) is **dynamically imported**: it is 353 kB of the app and is needed by
    two views, so the graph, report, plan and schedule now open on a 46 kB entry chunk
    instead of a 562 kB one. And the service worker runs **two caches with opposite
    rules** — cache-first for the content-hashed shell, network-first with a fallback for
    `GET /lessons/{id}`. Nothing else from the API is cached: a stale concept graph or a
    stale due queue is worse than an error, because the learner would act on it.

Optional flags (calendar, recovery-aware scheduling) are wired as feature-flagged
providers with a null default so the core build doesn't depend on them. **No real
provider ships** — `app/integrations/` defines a Protocol per capability and a null
implementation of each, and the resolvers return the null one whatever the flag says.
The seam is real and exercised on every schedule build; the capability is not. Adding a
provider means implementing one Protocol and changing one resolver.

## Risk notes

- **Propagation sign errors** are the most likely silent bug: edge direction plus the
  correct/incorrect asymmetry. Mitigated by a fixture graph with hand-computed expectations.
- **Selection starvation** — an information-gain rule that keeps picking the same node.
  Mitigated by excluding asked nodes and asserting spread in a test.
- **Plan ordering** must never place a unit before a prerequisite unit. Asserted directly
  over generated plans rather than trusted from the sequencer's shape.
