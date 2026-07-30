/**
 * The report: where the learner stands, and what is in the way.
 *
 * Coverage is stated as what it is -- mean estimated mastery -- and the count of
 * weakly-evidenced concepts is shown next to it, because a high coverage number
 * over an unassessed graph is a claim about a prior, not about the learner.
 */

import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { NodeScore } from "../api/types";
import { masteryColor } from "../components/GraphView";
import { useAsync } from "../hooks";
import { Stat } from "./GraphPage";

export function ReportView({ subjectId }: { subjectId: string }) {
  const { data, error, loading } = useAsync(() => api.getReport(subjectId), [subjectId]);

  if (error) return <p className="notice notice-danger">{error}</p>;
  if (loading && !data) return <p className="muted">Loading the report…</p>;
  if (!data) return null;

  return (
    <section className="stack">
      <div className="summary-row">
        <Stat label="Coverage" value={`${Math.round(data.coverage * 100)}%`} />
        <Stat label="Held" value={`${data.mastered_nodes}/${data.total_nodes}`} />
        <Stat label="Answered" value={String(data.diagnostic_responses)} />
      </div>

      <p className="muted">
        Coverage is the mean estimated mastery across every concept, not the number of
        lessons finished.
        {data.unassessed_nodes > 0 && (
          <>
            {" "}
            {data.unassessed_nodes} of {data.total_nodes} concepts still rest on inference
            rather than evidence.
          </>
        )}
      </p>

      {!data.has_plan && (
        <div className="panel">
          <h2>No plan yet</h2>
          <p className="muted">
            A plan sequences what is left so nothing is taught before what it depends on.
          </p>
          <Link className="btn btn-accent" to="../plan">
            Build one
          </Link>
        </div>
      )}

      <div className="panel">
        <h2>By tier</h2>
        <div className="tier-bars">
          {data.tiers.map((tier) => (
            <div key={tier.tier} className="tier-bar">
              <span className="tier-label">T{tier.tier}</span>
              <div className="bar">
                <div
                  className="bar-fill"
                  style={{
                    width: `${Math.round(tier.mean_mastery * 100)}%`,
                    background: masteryColor(tier.mean_mastery),
                  }}
                />
              </div>
              <span className="tier-value">
                {Math.round(tier.mean_mastery * 100)}%
                <span className="muted"> · {tier.mastered}/{tier.count}</span>
              </span>
            </div>
          ))}
        </div>
      </div>

      {data.blocking.target_tier !== null && (
        <div className="panel">
          <h2>What is in the way</h2>
          <p className="muted">
            Tier {data.blocking.target_tier} is the first one not yet cleared.
            {data.blocking.blocked.length > 0
              ? " These concepts are held up by prerequisites you have not got yet."
              : " Nothing upstream is holding it back, so the tier's own weak concepts are the thing to attack."}
          </p>
          <ScoreList scores={data.blocking.blockers} />
        </div>
      )}

      <div className="two-up">
        <div className="panel">
          <h2>Strengths</h2>
          {data.strengths.length > 0 ? (
            <ScoreList scores={data.strengths} />
          ) : (
            <p className="muted">Nothing has enough evidence behind it to call a strength yet.</p>
          )}
        </div>
        <div className="panel">
          <h2>Worth attacking</h2>
          <ScoreList scores={data.weaknesses} />
        </div>
      </div>

      <div className="panel">
        <h2>Spacing</h2>
        <p>{data.calibration.advice}</p>
        {data.calibration.success_rate !== null && (
          <p className="muted">
            {Math.round(data.calibration.success_rate * 100)}% recall over{" "}
            {data.calibration.sample_size} graded retrievals.
          </p>
        )}
      </div>

      {data.open_suggestions > 0 && (
        <div className="panel">
          <h2>The graph may be wrong</h2>
          <p className="muted">
            {data.open_suggestions} suggested change{data.open_suggestions === 1 ? "" : "s"} is
            waiting for review.
          </p>
          <Link className="btn" to="../changes">
            Review them
          </Link>
        </div>
      )}
    </section>
  );
}

function ScoreList({ scores }: { scores: NodeScore[] }) {
  if (scores.length === 0) return <p className="muted">Nothing to show.</p>;
  return (
    <ul className="score-list">
      {scores.map((score) => (
        <li key={score.node_id}>
          <span className="dot" style={{ background: masteryColor(score.mastery) }} />
          <span className="score-name">{score.name}</span>
          <span className="score-meta">
            {Math.round(score.mastery * 100)}%
            {score.unblocks > 0 && ` · unblocks ${score.unblocks}`}
          </span>
        </li>
      ))}
    </ul>
  );
}
