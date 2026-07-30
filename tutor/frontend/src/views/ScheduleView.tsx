/**
 * The schedule: cadence settings, the next fortnight, and the deadline verdict.
 *
 * The verdict is placed above the calendar on purpose. If the cadence cannot hit
 * the deadline, that is the most important thing on the page, and burying it under
 * a pretty two-week grid would be exactly the quiet lie the planner was written to
 * avoid.
 */

import { useCallback, useState } from "react";
import { api } from "../api/client";
import { useAsync, useSubject } from "../hooks";
import { Stat } from "./GraphPage";

export function ScheduleView({ subjectId }: { subjectId: string }) {
  const { subject, reload: reloadSubject } = useSubject(subjectId);
  const { data, error, loading, reload } = useAsync(
    () => api.getSchedule(subjectId),
    [subjectId],
  );
  const [busy, setBusy] = useState(false);

  const patch = useCallback(
    async (body: Record<string, unknown>) => {
      setBusy(true);
      try {
        await api.patchCadence(subjectId, body);
        reloadSubject();
        reload();
      } finally {
        setBusy(false);
      }
    },
    [reload, reloadSubject, subjectId],
  );

  const rebuild = useCallback(async () => {
    setBusy(true);
    try {
      await api.buildSchedule(subjectId);
      reload();
    } finally {
      setBusy(false);
    }
  }, [reload, subjectId]);

  const complete = useCallback(
    async (sessionId: string) => {
      await api.completeSession(sessionId);
      reload();
    },
    [reload],
  );

  if (error) return <p className="notice notice-danger">{error}</p>;
  if (loading && !data) return <p className="muted">Loading the schedule…</p>;
  if (!data) return null;

  return (
    <section className="stack">
      <div
        className={
          data.deadline.achievable ? "panel" : "panel panel-warn"
        }
      >
        <h2>{data.deadline.achievable ? "Pace" : "This will not fit"}</h2>
        <p>{data.deadline.message}</p>
        {data.units_remaining > 0 && (
          <p className="muted">
            {data.units_scheduled} units are in the next {data.horizon_days} days;{" "}
            {data.units_remaining} come after that.
          </p>
        )}
      </div>

      <div className="panel">
        <h2>Cadence</h2>
        <div className="cadence">
          <label className="field">
            <span>Days a week</span>
            <input
              type="number"
              min={1}
              max={7}
              value={subject?.days_per_week ?? data.days_per_week}
              disabled={busy}
              onChange={(event) => void patch({ days_per_week: Number(event.target.value) })}
            />
          </label>
          <label className="field">
            <span>Minutes a session</span>
            <input
              type="number"
              min={5}
              max={180}
              step={5}
              value={subject?.minutes_per_session ?? data.minutes_per_session}
              disabled={busy}
              onChange={(event) =>
                void patch({ minutes_per_session: Number(event.target.value) })
              }
            />
          </label>
          <label className="field">
            <span>Reviews a day, at most</span>
            <input
              type="number"
              min={1}
              max={200}
              value={subject?.daily_review_cap ?? data.daily_review_cap}
              disabled={busy}
              onChange={(event) => void patch({ daily_review_cap: Number(event.target.value) })}
            />
          </label>
          <label className="field">
            <span>Deadline</span>
            <input
              type="date"
              value={subject?.deadline ?? ""}
              disabled={busy}
              onChange={(event) => void patch({ deadline: event.target.value || null })}
            />
          </label>
        </div>
        <button type="button" className="btn" disabled={busy} onClick={() => void rebuild()}>
          {busy ? "Planning…" : "Rebuild the schedule"}
        </button>
      </div>

      <div className="summary-row">
        <Stat label="Completed" value={String(data.adherence.sessions_completed)} />
        <Stat label="Missed" value={String(data.adherence.sessions_missed)} />
        <Stat label="Streak" value={String(data.adherence.current_streak)} />
        <Stat
          label="Turned up"
          value={
            data.adherence.completion_rate === null
              ? "—"
              : `${Math.round(data.adherence.completion_rate * 100)}%`
          }
        />
      </div>

      <div className="panel">
        <h2>Next {data.horizon_days} days</h2>
        <ul className="session-list">
          {data.sessions.map((session) => (
            <li key={session.scheduled_for} className={`session is-${session.status}`}>
              <div className="session-when">
                <span className="session-day">
                  {new Date(`${session.scheduled_for}T00:00:00`).toLocaleDateString(undefined, {
                    weekday: "short",
                  })}
                </span>
                <span className="session-date">
                  {new Date(`${session.scheduled_for}T00:00:00`).toLocaleDateString(undefined, {
                    day: "numeric",
                    month: "short",
                  })}
                </span>
              </div>
              <div className="session-body">
                <p className="session-shape">
                  {session.review_names.length > 0
                    ? `${session.review_names.length} to retrieve`
                    : "no reviews due"}
                  {" · "}
                  {session.new_names.length > 0
                    ? `${session.new_names.length} new`
                    : "nothing new"}
                  {" · "}
                  {session.planned_minutes} min
                </p>
                {session.new_names.length > 0 && (
                  <p className="muted">{session.new_names.join(", ")}</p>
                )}
                {session.notes && <p className="muted">{session.notes}</p>}
              </div>
              {session.status === "planned" && session.id && (
                <button
                  type="button"
                  className="btn btn-quiet"
                  onClick={() => void complete(session.id!)}
                >
                  Done
                </button>
              )}
              {session.status !== "planned" && (
                <span className="chip">{session.status}</span>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
