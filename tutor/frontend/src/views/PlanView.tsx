/**
 * The plan: the sequence, and the unit currently open.
 *
 * Every unit shows the sequencer's reason for sitting where it does. That is not
 * decoration -- the spec's criterion is that every unit be *defensibly* positioned,
 * and a position you cannot see the argument for is not defensible, it is just
 * asserted.
 */

import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { NextUnit, UnitCompleteResult } from "../api/types";
import { useAsync } from "../hooks";

export function PlanView({ subjectId }: { subjectId: string }) {
  const { data: plan, error, loading, reload } = useAsync(
    () => api.getPlan(subjectId).catch(() => null),
    [subjectId],
  );
  const [creating, setCreating] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const create = useCallback(async () => {
    setCreating(true);
    setFailure(null);
    try {
      await api.createPlan(subjectId);
      reload();
    } catch (caught) {
      setFailure(caught instanceof Error ? caught.message : "Could not build a plan.");
    } finally {
      setCreating(false);
    }
  }, [reload, subjectId]);

  if (error) return <p className="notice notice-danger">{error}</p>;
  if (loading && plan === null) return <p className="muted">Loading the plan…</p>;

  if (!plan) {
    return (
      <section className="stack">
        <div className="panel">
          <h2>No plan yet</h2>
          <p className="muted">
            A plan orders what is left so no unit ever depends on something you have not been
            taught or tested on.
          </p>
          {failure && <p className="notice notice-danger">{failure}</p>}
          <button type="button" className="btn btn-accent" onClick={() => void create()}>
            {creating ? "Sequencing…" : "Build a plan"}
          </button>
        </div>
      </section>
    );
  }

  const done = plan.units.filter((unit) => unit.status === "complete" || unit.status === "skipped");

  return (
    <section className="stack">
      <div className="summary-row">
        <StatInline label="Units" value={`${done.length}/${plan.units.length}`} />
        <StatInline label="Coverage" value={`${Math.round(plan.coverage_now * 100)}%`} />
        <StatInline label="Already known" value={String(plan.skipped_mastered)} />
        <button type="button" className="btn btn-quiet" onClick={() => void create()}>
          Rebuild
        </button>
      </div>

      {plan.truncated > 0 && (
        <p className="notice notice-warn">
          This plan is a prefix: {plan.truncated} more concepts are not in it yet.
        </p>
      )}

      <ActiveUnit planId={plan.id} onCompleted={reload} />

      <div className="panel">
        <h2>The sequence</h2>
        <ol className="unit-list">
          {plan.units.map((unit) => (
            <li key={unit.id} className={`unit is-${unit.status}`}>
              <div className="unit-head">
                <span className="unit-seq">{unit.seq + 1}</span>
                <span className="unit-title">{unit.title}</span>
                <span className="chip">tier {unit.tier}</span>
                {unit.status !== "pending" && <span className="chip">{unit.status}</span>}
              </div>
              <p className="unit-objective">{unit.objective}</p>
              <p className="unit-reason">{unit.placement_reason}</p>
              {unit.interleaved_names.length > 0 && (
                <p className="muted">
                  Opens by retrieving {unit.interleaved_names.join(" and ")}.
                </p>
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function ActiveUnit({ planId, onCompleted }: { planId: string; onCompleted: () => void }) {
  const { data, error, reload } = useAsync<NextUnit>(() => api.nextUnit(planId), [planId]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<UnitCompleteResult | null>(null);
  const [busy, setBusy] = useState(false);

  const close = useCallback(
    async (skipped: boolean) => {
      if (!data?.unit || busy) return;
      setBusy(true);
      try {
        const payload = skipped
          ? []
          : data.exit_check
              .filter((item) => (answers[item.id] ?? "").trim())
              .map((item) => ({ item_id: item.id, answer: answers[item.id] ?? "" }));
        setResult(await api.completeUnit(data.unit.id, payload, skipped));
        setAnswers({});
        onCompleted();
      } finally {
        setBusy(false);
      }
    },
    [answers, busy, data, onCompleted],
  );

  if (error) return <p className="notice notice-danger">{error}</p>;
  if (!data) return null;
  if (data.finished || !data.unit) {
    return (
      <div className="panel">
        <h2>Plan complete</h2>
        <p className="muted">Every unit is done. Rebuild the plan to pick up what is left.</p>
      </div>
    );
  }

  if (result) {
    return (
      <div className="panel">
        <h2>Unit closed</h2>
        {result.exit_score !== null ? (
          <p>
            Exit check {Math.round(result.exit_score * 100)}% · {result.mastery_before < result.mastery_after ? "up" : "down"} from{" "}
            {Math.round(result.mastery_before * 100)}% to {Math.round(result.mastery_after * 100)}%.
          </p>
        ) : (
          <p className="muted">Closed without the exit check, so no evidence was gathered.</p>
        )}
        {result.feedback.map((line, index) => (
          <p key={index}>{line}</p>
        ))}
        <button
          type="button"
          className="btn btn-accent"
          onClick={() => {
            setResult(null);
            reload();
          }}
        >
          Next unit
        </button>
      </div>
    );
  }

  const unit = data.unit;
  return (
    <div className="panel panel-active">
      <div className="panel-head">
        <h2>Up next: {unit.title}</h2>
        <span className="chip">{unit.estimated_minutes} min</span>
      </div>
      <p>{unit.objective}</p>
      <p className="unit-reason">{unit.placement_reason}</p>

      <div className="row">
        {data.lesson_id && (
          <Link className="btn btn-accent" to={`lesson/${data.lesson_id}`}>
            Read the lesson
          </Link>
        )}
      </div>

      {data.exit_check.length > 0 && (
        <details className="details">
          <summary>Exit check ({data.exit_check.length} questions)</summary>
          <div className="stack-tight">
            {data.exit_check.map((item) => (
              <label key={item.id} className="field">
                <span>{item.stem}</span>
                <textarea
                  rows={3}
                  value={answers[item.id] ?? ""}
                  onChange={(event) =>
                    setAnswers((current) => ({ ...current, [item.id]: event.target.value }))
                  }
                />
              </label>
            ))}
            <div className="row">
              <button
                type="button"
                className="btn btn-accent"
                disabled={busy}
                onClick={() => void close(false)}
              >
                {busy ? "Grading…" : "Submit and close"}
              </button>
              <button
                type="button"
                className="btn btn-quiet"
                disabled={busy}
                onClick={() => void close(true)}
              >
                Close without answering
              </button>
            </div>
          </div>
        </details>
      )}
    </div>
  );
}

function StatInline({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
