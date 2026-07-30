/**
 * The diagnostic runner.
 *
 * One question at a time, with the graded feedback shown before the next question
 * is fetched -- the feedback names the specific gap, and skipping past it wastes
 * the most useful thing the grader produced.
 *
 * The mastery movement is shown too, including what the answer implied about
 * neighbouring concepts. That is the part people find surprising ("why did
 * answering *that* change *this*?") and showing it is what makes the model
 * arguable with rather than magic.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { AnswerResult, Item } from "../api/types";

export function DiagnosticView({ subjectId }: { subjectId: string }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [item, setItem] = useState<Item | null>(null);
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [finished, setFinished] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const advance = useCallback(async (id: string) => {
    setBusy(true);
    try {
      const next = await api.nextItem(id);
      if (next.finished || !next.item) {
        setFinished(next.stop_reason ?? "complete");
        setItem(null);
      } else {
        setItem(next.item);
        setAnswer("");
      }
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not fetch the next question.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    api
      .startDiagnostic(subjectId)
      .then(async (session) => {
        if (cancelled) return;
        setSessionId(session.id);
        await advance(session.id);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : "Could not start the diagnostic.");
        setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [subjectId, advance]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!sessionId || !item || busy || !answer.trim()) return;
    setBusy(true);
    try {
      setResult(await api.answer(sessionId, item.id, answer));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not submit that answer.");
    } finally {
      setBusy(false);
    }
  }

  async function next() {
    if (!sessionId) return;
    setResult(null);
    await advance(sessionId);
  }

  if (error) return <p className="notice notice-danger">{error}</p>;

  if (finished) {
    return (
      <section className="stack">
        <div className="panel">
          <h2>Diagnostic complete</h2>
          <p className="muted">
            {finished === "confidence_target"
              ? "The estimate settled before the question cap, so there was nothing more worth asking."
              : "That is the full set of questions."}
          </p>
          <div className="row">
            <Link className="btn btn-accent" to="../report">
              See the report
            </Link>
            <Link className="btn" to="../graph">
              Back to the graph
            </Link>
          </div>
        </div>
      </section>
    );
  }

  if (!item) return <p className="muted">Choosing the most informative question…</p>;

  return (
    <section className="stack">
      <div className="progress" aria-label="Progress">
        <div
          className="progress-fill"
          style={{ width: `${Math.round((item.asked_count / item.max_items) * 100)}%` }}
        />
      </div>
      <p className="muted">
        Question {item.asked_count + 1} of at most {item.max_items} · {item.node_name} · tier{" "}
        {item.tier}
      </p>

      <div className="panel">
        <p className="stem">{item.stem}</p>

        {!result && (
          <form onSubmit={submit} className="stack-tight">
            {item.item_format === "multiple_choice" ? (
              <div className="choices">
                {item.choices.map((choice, index) => (
                  <label
                    key={choice}
                    className={answer === String(index) ? "choice is-chosen" : "choice"}
                  >
                    <input
                      type="radio"
                      name="choice"
                      value={String(index)}
                      checked={answer === String(index)}
                      onChange={(event) => setAnswer(event.target.value)}
                    />
                    <span>{choice}</span>
                  </label>
                ))}
              </div>
            ) : (
              <textarea
                value={answer}
                rows={5}
                placeholder="Answer in a sentence or three."
                onChange={(event) => setAnswer(event.target.value)}
                aria-label="Your answer"
              />
            )}
            <button type="submit" className="btn btn-accent" disabled={busy || !answer.trim()}>
              {busy ? "Grading…" : "Submit"}
            </button>
          </form>
        )}

        {result && (
          <div className="stack-tight">
            <p className={result.correct ? "verdict is-good" : "verdict is-bad"}>
              {result.correct ? "Correct" : "Not quite"} · {Math.round(result.score * 100)}%
            </p>
            <p>{result.feedback}</p>
            {result.misconception && (
              <p className="notice notice-warn">
                <strong>Worth naming:</strong> {result.misconception}
              </p>
            )}
            {!result.correct && (
              <p className="muted">
                <strong>Reference answer.</strong> {result.answer_key}
              </p>
            )}
            <MasteryDelta result={result} />
            <button type="button" className="btn btn-accent" onClick={() => void next()}>
              Next question
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function MasteryDelta({ result }: { result: AnswerResult }) {
  const direct = result.changes.find((change) => !change.propagated);
  const propagated = result.changes.filter((change) => change.propagated);
  if (!direct) return null;
  return (
    <details className="details">
      <summary>
        {direct.node_name} {Math.round(direct.mastery_before * 100)}% →{" "}
        {Math.round(direct.mastery_after * 100)}%
        {propagated.length > 0 && `, and ${propagated.length} related concepts moved`}
      </summary>
      <ul className="delta-list">
        {propagated.map((change) => (
          <li key={change.node_id}>
            {change.node_name} {Math.round(change.mastery_before * 100)}% →{" "}
            {Math.round(change.mastery_after * 100)}%
          </li>
        ))}
      </ul>
      <p className="muted">
        An answer says something about a concept&rsquo;s prerequisites and about what depends
        on it, so those estimates move too.
      </p>
    </details>
  );
}
