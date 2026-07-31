/**
 * The concept graph, drawn as a layered DAG in hand-written SVG.
 *
 * No graph library. A force-directed layout is the wrong shape for this data: the
 * graph *has* a canonical vertical order -- tier 1 at the bottom, tier 5 at the
 * top -- and a physics simulation throws that away in exchange for a pleasing
 * wobble. A layered DAG puts prerequisites below what they unlock, which is the
 * one thing the learner needs to read off the picture. It also lays out
 * deterministically, so the graph does not rearrange itself between visits.
 *
 * The encoding, all four channels from the spec:
 *
 * * **Fill = mastery**, on the dedicated mastery scale (slate to blue to green).
 * * **Opacity = confidence.** A node the app is guessing about looks like a guess.
 * * **Ring = high confidence.** A solid outline means the estimate is earned.
 * * **Greyed edge = locked prerequisite**, i.e. an edge whose source is not yet
 *   mastered, so the path through it is not currently open.
 *
 * Phone readability drove two decisions: within a tier, nodes are ordered by the
 * average horizontal position of their prerequisites (a barycentre pass) so edges
 * mostly run straight up rather than crossing the whole width; and the SVG scrolls
 * horizontally inside its own container rather than shrinking to fit, because a
 * hundred nodes squeezed into 360 pixels is not a diagram, it is a texture.
 */

import { useMemo } from "react";
import type { Graph, GraphNode } from "../api/types";

const NODE_R = 13;
const COL_GAP = 74;
const ROW_GAP = 116;
const PAD = 40;

export interface Placed {
  node: GraphNode;
  x: number;
  y: number;
}

export interface GraphViewProps {
  graph: Graph;
  selectedId?: string | null;
  onSelect?: (nodeId: string) => void;
  /** Concepts to outline, e.g. the units of the current plan. */
  highlightIds?: readonly string[];
}

/** Bucket a mastery estimate onto the design system's mastery scale. */
export function masteryColor(mastery: number): string {
  if (mastery >= 0.85) return "var(--mastery-5)";
  if (mastery >= 0.7) return "var(--mastery-4)";
  if (mastery >= 0.5) return "var(--mastery-3)";
  if (mastery >= 0.3) return "var(--mastery-2)";
  return "var(--mastery-1)";
}

/** Lay the graph out in tiers, ordering each tier to minimise edge crossings. */
export function layout(graph: Graph): { placed: Placed[]; width: number; height: number } {
  const tiers = [...new Set(graph.nodes.map((n) => n.tier))].sort((a, b) => a - b);
  const byTier = new Map<number, GraphNode[]>();
  for (const tier of tiers) {
    byTier.set(
      tier,
      graph.nodes.filter((n) => n.tier === tier).sort((a, b) => a.name.localeCompare(b.name)),
    );
  }

  const prereqsOf = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const list = prereqsOf.get(edge.node_id) ?? [];
    list.push(edge.prereq_id);
    prereqsOf.set(edge.node_id, list);
  }

  const columnOf = new Map<string, number>();
  // Bottom tier keeps alphabetical order; every tier above sorts by the mean
  // column of its prerequisites, so edges tend to run straight up.
  tiers.forEach((tier, index) => {
    const members = byTier.get(tier) ?? [];
    const ordered =
      index === 0
        ? members
        : [...members].sort((a, b) => barycentre(a, columnOf, prereqsOf) - barycentre(b, columnOf, prereqsOf));
    ordered.forEach((node, column) => columnOf.set(node.id, column));
    byTier.set(tier, ordered);
  });

  // Both dimensions are floored at the padding. With no tiers at all the row term
  // is negative, and an SVG with a negative height is invalid markup -- the
  // component happens to return early on an empty graph, but the layout function
  // must not depend on its caller doing that.
  const widest = Math.max(1, ...tiers.map((t) => (byTier.get(t) ?? []).length));
  const width = Math.max(PAD * 2, PAD * 2 + (widest - 1) * COL_GAP);
  const height = Math.max(PAD * 2, PAD * 2 + (tiers.length - 1) * ROW_GAP);

  const placed: Placed[] = [];
  tiers.forEach((tier, index) => {
    const members = byTier.get(tier) ?? [];
    // Centre each tier, so a narrow top tier sits over the middle of a wide base.
    const offset = (width - (members.length - 1) * COL_GAP) / 2;
    members.forEach((node, column) => {
      placed.push({
        node,
        x: offset + column * COL_GAP,
        y: height - PAD - index * ROW_GAP,
      });
    });
  });
  return { placed, width, height };
}

function barycentre(
  node: GraphNode,
  columnOf: Map<string, number>,
  prereqsOf: Map<string, string[]>,
): number {
  const prereqs = (prereqsOf.get(node.id) ?? [])
    .map((id) => columnOf.get(id))
    .filter((c): c is number => c !== undefined);
  if (prereqs.length === 0) return Number.MAX_SAFE_INTEGER;
  return prereqs.reduce((a, b) => a + b, 0) / prereqs.length;
}

export function GraphView({ graph, selectedId, onSelect, highlightIds = [] }: GraphViewProps) {
  const { placed, width, height } = useMemo(() => layout(graph), [graph]);
  const positions = useMemo(
    () => new Map(placed.map((p) => [p.node.id, p])),
    [placed],
  );
  const highlighted = useMemo(() => new Set(highlightIds), [highlightIds]);

  if (graph.nodes.length === 0) {
    return <p className="muted">This graph has no concepts yet.</p>;
  }

  return (
    <div className="graph-scroll" role="group" aria-label="Concept graph">
      <svg
        className="graph"
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        aria-label={`${graph.nodes.length} concepts across ${new Set(graph.nodes.map((n) => n.tier)).size} tiers`}
      >
        <g className="graph-edges">
          {graph.edges.map((edge) => {
            const from = positions.get(edge.prereq_id);
            const to = positions.get(edge.node_id);
            if (!from || !to) return null;
            // The server decides what "locked" means -- one definition of "can the
            // learner cross this yet", rather than a client-side copy of the
            // threshold that drifts the first time the threshold is configured.
            const locked = edge.locked;
            const touching =
              selectedId === edge.prereq_id || selectedId === edge.node_id;
            return (
              <line
                key={`${edge.prereq_id}-${edge.node_id}`}
                className={
                  "graph-edge" +
                  (locked ? " is-locked" : "") +
                  (touching ? " is-touching" : "")
                }
                x1={from.x}
                y1={from.y - NODE_R}
                x2={to.x}
                y2={to.y + NODE_R}
              />
            );
          })}
        </g>
        <g className="graph-nodes">
          {placed.map(({ node, x, y }) => {
            const confident = node.confidence >= 0.45;
            return (
              <g
                key={node.id}
                className={
                  "graph-node" +
                  (selectedId === node.id ? " is-selected" : "") +
                  (highlighted.has(node.id) ? " is-highlighted" : "") +
                  (node.locked ? " is-locked" : "")
                }
                transform={`translate(${x} ${y})`}
                tabIndex={0}
                role="button"
                aria-label={`${node.name}, tier ${node.tier}, mastery ${Math.round(node.mastery * 100)} percent`}
                onClick={() => onSelect?.(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect?.(node.id);
                  }
                }}
              >
                {/* Invisible, generously sized hit area: the visible dot is 26px
                    across, well under the 44px minimum touch target. */}
                <circle className="graph-hit" r={24} />
                <circle
                  className="graph-dot"
                  r={NODE_R}
                  fill={masteryColor(node.mastery)}
                  // Confidence is opacity, floored so a seeded node is still visible.
                  opacity={0.35 + 0.65 * node.confidence}
                />
                {confident && <circle className="graph-ring" r={NODE_R + 4} />}
                <title>
                  {node.name} — mastery {Math.round(node.mastery * 100)}%, confidence{" "}
                  {Math.round(node.confidence * 100)}%
                </title>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

export function GraphLegend() {
  return (
    <div className="legend" aria-label="How to read the graph">
      <span className="legend-item">
        <span className="legend-swatch" style={{ background: "var(--mastery-1)" }} /> not yet known
      </span>
      <span className="legend-item">
        <span className="legend-swatch" style={{ background: "var(--mastery-3)" }} /> partial
      </span>
      <span className="legend-item">
        <span className="legend-swatch" style={{ background: "var(--mastery-5)" }} /> held
      </span>
      <span className="legend-item">
        <span className="legend-swatch legend-faint" /> faded means low confidence
      </span>
      <span className="legend-item">
        <span className="legend-swatch legend-ring" /> ring means the estimate is earned
      </span>
    </div>
  );
}
