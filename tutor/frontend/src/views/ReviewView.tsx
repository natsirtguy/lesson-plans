/**
 * The review queue.
 *
 * The queue is shown before the questions, because "seven things are due and four
 * more were pushed to tomorrow" is information the learner acts on, and a UI that
 * hands over one question at a time hides it.
 */

import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { ReviewItem, ReviewResult } from "../api/types";
import { masteryColor } from "../components/GraphView";
import { useAsync } from "../hooks";
import { Stat } from "./GraphPage";

export function ReviewView({ subjectId }: { subjectId: string }) {
  const { data: queue, error, loading, reload } = useAsync(
    () => api.getDue(subjectId),
    [subjectId],
  );
  const [item, setItem] = useState<ReviewItem | null>(null);
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const draw = useCallback(async () => {
    setBusy(true);
    setResult(null);
    setAnswer("");
    setFailure(null);
    try {
      setItem(await api.nextReview(subjectId));
    } catch (caught) {
      setItem(null);
      setFailure(caught instanceof Error ? caught.message : "Nothing is due.");
    } finally {
      setBusy(false);
    }
  }, [subjectId]);

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      if (!item || busy || !answer.trim()) return;
      setBusy(true);
      try {
        setResult(await api.answerReview(subjectId, item.id, answer));
        reload();
      } catch (caught) {
        setFailure(caught instanceof Error ? caught.message : "Could not grade that.");
      } finally {
        setBusy(false);
      }
    },
    [answer, busy, item, reload, subjectId],
  );

  if (error) return <p className="notice notice-danger">{error}</p>;
  if (loading && !queue) return <p className="muted">Loading the queue…</p>;
  if (!queue) return null;

  return (
    <section className="stack">
      <div className="summary-row">
        <Stat label="Due now" value={String(queue.due.length)} />
        <Stat label="Deferred" value={String(queue.deferred)} />
        <Stat label="Tracked" value={String(queue.total_cards)} />
        {queue.due.length > 0 && !item && (
          <button type="button" className="btn btn-accent" onClick={() => void draw()}>
            Start reviewing
          </button>
        )}
      </div>

      {queue.deferred > 0 && (
        <p className="notice notice-warn">
          {queue.deferred} more {queue.deferred === 1 ? "concept is" : "concepts are"} due but
          over today&rsquo;s cap of {queue.daily_cap}. They lead tomorrow&rsquo;s queue.
        </p>
      )}

      {item && (
        <div className="panel">
          <p className="muted">
            {item.node_name} · tier {item.tier} · {item.remaining} left
          </p>
          <p className="stem">{item.stem}</p>

          {!result ? (
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
                        name="review-choice"
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
                  rows={4}
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                  aria-label="Your answer"
                />
              )}
              <button type="submit" className="btn btn-accent" disabled={busy || !answer.trim()}>
                {busy ? "Grading…" : "Submit"}
              </button>
            </form>
          ) : (
            <div className="stack-tight">
              <p className={result.correct ? "verdict is-good" : "verdict is-bad"}>
                {result.correct ? "Held" : "Slipped"} · {Math.round(result.score * 100)}%
              </p>
              <p>{result.feedback}</p>
              <p className="muted">
                Next in {formatInterval(result.interval_days)} — {result.schedule_reason}.
              </p>
              {result.remaining > 0 ? (
                <button type="button" className="btn btn-accent" onClick={() => void draw()}>
                  Next ({result.remaining} left)
                </button>
              ) : (
                <p className="muted">That clears today&rsquo;s queue.</p>
              )}
            </div>
          )}
        </div>
      )}

      {failure && !item && <p className="notice">{failure}</p>}

      {queue.due.length === 0 && queue.upcoming.length > 0 && (
        <div className="panel">
          <h2>Coming up</h2>
          <ul className="score-list">
            {queue.upcoming.map((card) => (
              <li key={card.node_id}>
                <span className="dot" style={{ background: masteryColor(card.mastery) }} />
                <span className="score-name">{card.node_name}</span>
                <span className="score-meta">
                  {card.due_at ? new Date(card.due_at).toLocaleDateString() : "—"} ·{" "}
                  {Math.round(card.retrievability * 100)}% recall
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {queue.total_cards === 0 && (
        <p className="muted">
          Nothing is scheduled yet. Concepts join the review queue once a unit&rsquo;s exit
          check has been answered.
        </p>
      )}
    </section>
  );
}

function formatInterval(days: number): string {
  if (days < 1) return `${Math.max(1, Math.round(days * 24 * 60))} minutes`;
  if (days < 60) return `${Math.round(days)} day${Math.round(days) === 1 ? "" : "s"}`;
  return `${Math.round(days / 30)} months`;
}
