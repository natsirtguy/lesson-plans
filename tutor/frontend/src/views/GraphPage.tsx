/**
 * The graph page: the concept map, and an inspector for whatever is selected.
 *
 * This is the app's home screen. It answers "where am I" before it offers to do
 * anything, which is why the diagnostic and the plan are entry points *from* here
 * rather than the landing view.
 */

import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { GraphLegend, GraphView, masteryColor } from "../components/GraphView";
import { useAsync, useSubject } from "../hooks";

export function GraphPage({ subjectId }: { subjectId: string }) {
  const { subject } = useSubject(subjectId);
  const { data: graph, error, loading, reload } = useAsync(
    () => api.getGraph(subjectId),
    [subjectId],
  );
  const [selected, setSelected] = useState<string | null>(null);

  if (subject && subject.graph_status !== "ready") {
    return (
      <section className="stack">
        <div className="panel">
          <h2>Building the concept graph</h2>
          <p className="muted">
            {subject.graph_status === "failed"
              ? (subject.graph_error ?? "Generation failed.")
              : "Decomposing the subject into concepts and prerequisites. This page updates itself."}
          </p>
          {subject.graph_status === "failed" && (
            <button type="button" className="btn" onClick={reload}>
              Try again
            </button>
          )}
        </div>
      </section>
    );
  }

  if (error) return <p className="notice notice-danger">{error}</p>;
  if (loading && !graph) return <p className="muted">Loading the graph…</p>;
  if (!graph) return null;

  const node = graph.nodes.find((candidate) => candidate.id === selected) ?? null;
  const prereqs = node
    ? graph.edges
        .filter((edge) => edge.node_id === node.id)
        .map((edge) => graph.nodes.find((n) => n.id === edge.prereq_id))
        .filter((n) => n !== undefined)
    : [];

  return (
    <section className="stack">
      <div className="summary-row">
        <Stat label="Coverage" value={`${Math.round(graph.coverage * 100)}%`} />
        <Stat label="Concepts" value={String(graph.nodes.length)} />
        <Stat
          label="Held"
          value={String(graph.nodes.filter((n) => n.mastery >= 0.7).length)}
        />
        <Link className="btn btn-accent" to="../diagnostic">
          Run a diagnostic
        </Link>
      </div>

      <GraphView graph={graph} selectedId={selected} onSelect={setSelected} />
      <GraphLegend />

      {node ? (
        <div className="panel">
          <div className="panel-head">
            <span
              className="dot"
              style={{ background: masteryColor(node.mastery) }}
              aria-hidden="true"
            />
            <h2>{node.name}</h2>
            <span className="chip">tier {node.tier}</span>
          </div>
          <p>{node.definition}</p>
          <dl className="facts">
            <div>
              <dt>Mastery</dt>
              <dd>{Math.round(node.mastery * 100)}%</dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd>{Math.round(node.confidence * 100)}%</dd>
            </div>
            <div>
              <dt>Unblocks</dt>
              <dd>{node.unblocks}</dd>
            </div>
          </dl>
          <p className="muted">
            {node.ready
              ? "Every prerequisite is held, so this is available to study now."
              : node.locked
                ? "Nothing currently leads here: every prerequisite is itself unmastered."
                : "Some prerequisites are still in progress."}
          </p>
          {prereqs.length > 0 && (
            <p className="muted">
              Builds on{" "}
              {prereqs.map((prereq, index) => (
                <span key={prereq.id}>
                  {index > 0 && ", "}
                  <button
                    type="button"
                    className="link"
                    onClick={() => setSelected(prereq.id)}
                  >
                    {prereq.name}
                  </button>
                </span>
              ))}
              .
            </p>
          )}
        </div>
      ) : (
        <p className="muted">Tap a concept to see where it sits.</p>
      )}
    </section>
  );
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
