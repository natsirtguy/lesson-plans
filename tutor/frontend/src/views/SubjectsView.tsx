/** The landing page: pick a subject, or name a new one. */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../hooks";

export function SubjectsView() {
  const { data, error, loading, reload } = useAsync(() => api.listSubjects(), []);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const navigate = useNavigate();

  async function create(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const subject = await api.createSubject(trimmed);
      navigate(`/subjects/${subject.id}/graph`);
    } catch (caught) {
      setFailure(caught instanceof Error ? caught.message : "Could not create that subject.");
      setBusy(false);
    }
  }

  return (
    <div className="shell">
      <header className="shell-header">
        <div className="shell-title">
          <h1>Tutor</h1>
        </div>
      </header>

      <main className="shell-main">
        <section className="stack">
          <form className="new-subject" onSubmit={create}>
            <label htmlFor="subject-name">What do you want to learn?</label>
            <div className="row">
              <input
                id="subject-name"
                type="text"
                value={name}
                placeholder="Statistical mechanics"
                onChange={(event) => setName(event.target.value)}
              />
              <button type="submit" className="btn btn-accent" disabled={busy || !name.trim()}>
                {busy ? "Starting…" : "Start"}
              </button>
            </div>
            <p className="muted">
              Naming a subject builds a concept graph for it. That takes a minute; you can
              watch it arrive.
            </p>
          </form>

          {failure && <p className="notice notice-danger">{failure}</p>}
          {error && <p className="notice notice-danger">{error}</p>}
          {loading && !data && <p className="muted">Loading…</p>}

          {data && data.length > 0 && (
            <ul className="card-list">
              {data.map((subject) => (
                <li key={subject.id}>
                  <Link to={`/subjects/${subject.id}/graph`} className="card">
                    <span className="card-title">{subject.name}</span>
                    <span className="card-meta">
                      {subject.graph_status === "ready"
                        ? `${subject.node_count} concepts`
                        : subject.graph_status}
                      {" · "}
                      {subject.days_per_week} days a week
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          {data && data.length === 0 && (
            <p className="muted">Nothing here yet. Name a subject above.</p>
          )}
        </section>

        <button type="button" className="btn btn-quiet" onClick={reload}>
          Refresh
        </button>
      </main>
    </div>
  );
}
