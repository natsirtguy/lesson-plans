/**
 * Graph refinement: describe the problem, review the changeset, commit what you
 * accept.
 *
 * Per-operation accept/reject is the whole point, and the UI is built so that
 * committing everything is a *choice* rather than the path of least resistance:
 * every operation has its own checkbox and its own rationale, and the preview
 * revalidates against exactly the set that is currently ticked. If a subset would
 * be invalid -- a cycle, an orphan, a removed concept the plan still needs -- the
 * commit button is disabled and the reason is shown, rather than the server
 * rejecting it after the fact.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Changeset, ChangesetPreview } from "../api/types";
import { useAsync } from "../hooks";

export function ChangesetsView({ subjectId }: { subjectId: string }) {
  const [request, setRequest] = useState("");
  const [changeset, setChangeset] = useState<Changeset | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const suggestions = useAsync(() => api.listSuggestions(subjectId), [subjectId]);
  const history = useAsync(() => api.listChangesets(subjectId), [subjectId]);

  const propose = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      if (!request.trim() || busy) return;
      setBusy(true);
      setError(null);
      try {
        setChangeset(await api.refine(subjectId, request.trim()));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Could not propose a change.");
      } finally {
        setBusy(false);
      }
    },
    [busy, request, subjectId],
  );

  return (
    <section className="stack">
      <div className="panel">
        <h2>Tell it what is wrong</h2>
        <p className="muted">
          Plain language. &ldquo;Split entropy into the thermodynamic and information
          senses&rdquo;, or &ldquo;this is too shallow on measure theory&rdquo;. Nothing is
          applied until you approve it, operation by operation.
        </p>
        <form onSubmit={propose} className="stack-tight">
          <textarea
            rows={3}
            value={request}
            placeholder="What should be different about this graph?"
            onChange={(event) => setRequest(event.target.value)}
            aria-label="Refinement request"
          />
          <button type="submit" className="btn btn-accent" disabled={busy || !request.trim()}>
            {busy ? "Thinking…" : "Propose changes"}
          </button>
        </form>
        {error && <p className="notice notice-danger">{error}</p>}
      </div>

      {changeset && (
        <ChangesetReview
          subjectId={subjectId}
          changeset={changeset}
          onCommitted={() => {
            setChangeset(null);
            setRequest("");
            history.reload();
            suggestions.reload();
          }}
        />
      )}

      {suggestions.data && suggestions.data.length > 0 && (
        <div className="panel">
          <h2>Noticed while you were studying</h2>
          <ul className="score-list">
            {suggestions.data.map((suggestion) => (
              <li key={suggestion.id}>
                <span className="score-name">{suggestion.summary}</span>
                <button
                  type="button"
                  className="btn btn-quiet"
                  onClick={() => {
                    void api.dismissSuggestion(suggestion.id).then(suggestions.reload);
                  }}
                >
                  Dismiss
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {history.data && history.data.length > 0 && (
        <div className="panel">
          <h2>History</h2>
          <ul className="score-list">
            {history.data.map((entry) => (
              <li key={entry.id}>
                <span className="score-name">{entry.request || entry.rationale}</span>
                <span className="score-meta">
                  {entry.status}
                  {entry.graph_version_after !== null && ` · v${entry.graph_version_after}`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ChangesetReview({
  subjectId,
  changeset,
  onCommitted,
}: {
  subjectId: string;
  changeset: Changeset;
  onCommitted: () => void;
}) {
  const [accepted, setAccepted] = useState<Set<string>>(
    () => new Set(changeset.operations.map((op) => op.id)),
  );
  const [preview, setPreview] = useState<ChangesetPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .previewChangeset(changeset.id, [...accepted])
      .then((result) => {
        if (!cancelled) setPreview(result);
      })
      .catch(() => {
        if (!cancelled) setPreview(null);
      });
    return () => {
      cancelled = true;
    };
  }, [accepted, changeset.id]);

  async function commit() {
    setBusy(true);
    setError(null);
    try {
      await api.commitChangeset(subjectId, changeset.id, [...accepted]);
      onCommitted();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not commit.");
    } finally {
      setBusy(false);
    }
  }

  if (changeset.operations.length === 0) {
    return (
      <div className="panel">
        <h2>No change needed</h2>
        <p>{changeset.rationale}</p>
      </div>
    );
  }

  return (
    <div className="panel panel-active">
      <h2>Proposed changes</h2>
      <p>{changeset.rationale}</p>

      <ul className="op-list">
        {changeset.operations.map((op) => {
          const on = accepted.has(op.id);
          return (
            <li key={op.id} className={on ? "op is-on" : "op"}>
              <label className="op-toggle">
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() =>
                    setAccepted((current) => {
                      const next = new Set(current);
                      if (next.has(op.id)) next.delete(op.id);
                      else next.add(op.id);
                      return next;
                    })
                  }
                />
                <span className={`op-kind op-${op.op_type}`}>{op.op_type.replace("_", " ")}</span>
                <span className="op-summary">{op.summary}</span>
              </label>
              <p className="op-rationale">{op.rationale}</p>
            </li>
          );
        })}
      </ul>

      <div className="row">
        <button
          type="button"
          className="btn btn-quiet"
          onClick={() => setAccepted(new Set())}
        >
          Reject all
        </button>
        <button
          type="button"
          className="btn btn-quiet"
          onClick={() => setAccepted(new Set(changeset.operations.map((op) => op.id)))}
        >
          Accept all
        </button>
      </div>

      {preview && (
        <div className={preview.valid ? "preview" : "preview is-invalid"}>
          {preview.valid ? (
            <>
              <p className="muted">
                {preview.summary.length > 0
                  ? preview.summary.join(" · ")
                  : "Nothing selected."}
              </p>
              {preview.affected_node_ids.length > 0 && (
                <p className="muted">
                  {preview.affected_node_ids.length} concepts affected, {preview.edges_changed}{" "}
                  prerequisite edges changed.
                </p>
              )}
            </>
          ) : (
            <p>
              <strong>This selection would break the graph.</strong> {preview.error}
            </p>
          )}
        </div>
      )}

      {error && <p className="notice notice-danger">{error}</p>}

      <button
        type="button"
        className="btn btn-accent"
        disabled={busy || accepted.size === 0 || preview?.valid === false}
        onClick={() => void commit()}
      >
        {busy
          ? "Committing…"
          : `Commit ${accepted.size} of ${changeset.operations.length}`}
      </button>
    </div>
  );
}
