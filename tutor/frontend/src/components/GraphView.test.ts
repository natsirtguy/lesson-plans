/**
 * Tests for the graph layout.
 *
 * Three properties matter and none of them is visual. Prerequisites must sit
 * *below* what they unlock, or the picture asserts the opposite of the data. The
 * layout must be deterministic, or the graph rearranges itself between visits and
 * the learner loses their spatial memory of it. And the barycentre pass has to
 * actually reduce crossings, or it is cost without benefit.
 */

import { describe, expect, it } from "vitest";
import { layout, masteryColor } from "./GraphView";
import type { Graph, GraphEdge, GraphNode } from "../api/types";

function node(id: string, tier: number, name = id): GraphNode {
  return {
    id,
    name,
    definition: `Definition of ${name}.`,
    tier,
    mastery: 0.2,
    confidence: 0.3,
    unblocks: 0,
    locked: false,
    ready: false,
  };
}

function graphOf(nodes: GraphNode[], edges: [string, string][]): Graph {
  return {
    subject_id: "s",
    graph_version: 1,
    nodes,
    edges: edges.map(
      ([prereq_id, node_id]): GraphEdge => ({ prereq_id, node_id, locked: true }),
    ),
    graph_status: "ready",
    coverage: 0.2,
  };
}

/** Count edges whose endpoints cross another edge's endpoints horizontally. */
function crossings(graph: Graph): number {
  const { placed } = layout(graph);
  const at = new Map(placed.map((entry) => [entry.node.id, entry]));
  let total = 0;
  for (let i = 0; i < graph.edges.length; i++) {
    for (let j = i + 1; j < graph.edges.length; j++) {
      const a = graph.edges[i]!;
      const b = graph.edges[j]!;
      const a1 = at.get(a.prereq_id);
      const a2 = at.get(a.node_id);
      const b1 = at.get(b.prereq_id);
      const b2 = at.get(b.node_id);
      if (!a1 || !a2 || !b1 || !b2) continue;
      if (a1.y !== b1.y || a2.y !== b2.y) continue;
      if ((a1.x - b1.x) * (a2.x - b2.x) < 0) total++;
    }
  }
  return total;
}

describe("layout", () => {
  it("places a prerequisite below the concept it unlocks", () => {
    const graph = graphOf([node("base", 1), node("top", 2)], [["base", "top"]]);
    const { placed } = layout(graph);
    const base = placed.find((entry) => entry.node.id === "base")!;
    const top = placed.find((entry) => entry.node.id === "top")!;

    // SVG y grows downward, so "below" means a larger y.
    expect(base.y).toBeGreaterThan(top.y);
  });

  it("puts every concept of a tier on the same row", () => {
    const graph = graphOf(
      [node("a", 1), node("b", 1), node("c", 2), node("d", 2)],
      [
        ["a", "c"],
        ["b", "d"],
      ],
    );
    const { placed } = layout(graph);
    const rows = new Map<number, Set<number>>();
    for (const entry of placed) {
      rows.set(entry.node.tier, (rows.get(entry.node.tier) ?? new Set()).add(entry.y));
    }
    expect([...rows.values()].every((ys) => ys.size === 1)).toBe(true);
  });

  it("is deterministic", () => {
    const build = () =>
      graphOf(
        [node("a", 1), node("b", 1), node("c", 2), node("d", 2), node("e", 3)],
        [
          ["a", "c"],
          ["b", "d"],
          ["c", "e"],
          ["d", "e"],
        ],
      );
    const first = layout(build()).placed.map((entry) => [entry.node.id, entry.x, entry.y]);
    const second = layout(build()).placed.map((entry) => [entry.node.id, entry.x, entry.y]);
    expect(first).toEqual(second);
  });

  it("does not depend on the order nodes arrive in", () => {
    const nodes = [node("a", 1), node("b", 1), node("c", 2)];
    const edges: [string, string][] = [
      ["a", "c"],
      ["b", "c"],
    ];
    const forward = layout(graphOf(nodes, edges)).placed;
    const reversed = layout(graphOf([...nodes].reverse(), edges)).placed;

    const key = (entries: typeof forward) =>
      entries.map((entry) => `${entry.node.id}@${entry.x},${entry.y}`).sort();
    expect(key(forward)).toEqual(key(reversed));
  });

  it("orders an upper tier to avoid crossing its own edges", () => {
    // Named so alphabetical order is the *worst* order: z depends on the leftmost
    // base, a on the rightmost. Without a barycentre pass these edges cross.
    const graph = graphOf(
      [node("b1", 1), node("b2", 1), node("z", 2), node("a", 2)],
      [
        ["b1", "z"],
        ["b2", "a"],
      ],
    );
    expect(crossings(graph)).toBe(0);
  });

  it("places every node exactly once", () => {
    const nodes = Array.from({ length: 25 }, (_, index) =>
      node(`n${index}`, (index % 5) + 1),
    );
    const { placed } = layout(graphOf(nodes, []));
    expect(placed).toHaveLength(25);
    expect(new Set(placed.map((entry) => entry.node.id)).size).toBe(25);
  });

  it("handles an empty graph without producing a negative canvas", () => {
    const { placed, width, height } = layout(graphOf([], []));
    expect(placed).toEqual([]);
    expect(width).toBeGreaterThan(0);
    expect(height).toBeGreaterThanOrEqual(0);
  });

  it("handles a single node", () => {
    const { placed, width } = layout(graphOf([node("only", 3)], []));
    expect(placed).toHaveLength(1);
    expect(placed[0]!.x).toBeGreaterThanOrEqual(0);
    expect(placed[0]!.x).toBeLessThanOrEqual(width);
  });

  it("keeps every node inside the reported canvas", () => {
    const nodes = [node("a", 1), node("b", 1), node("c", 1), node("d", 2)];
    const { placed, width, height } = layout(
      graphOf(nodes, [
        ["a", "d"],
        ["b", "d"],
      ]),
    );
    for (const entry of placed) {
      expect(entry.x).toBeGreaterThanOrEqual(0);
      expect(entry.x).toBeLessThanOrEqual(width);
      expect(entry.y).toBeGreaterThanOrEqual(0);
      expect(entry.y).toBeLessThanOrEqual(height);
    }
  });

  it("centres a narrow tier over a wide one", () => {
    const graph = graphOf(
      [node("a", 1), node("b", 1), node("c", 1), node("top", 2)],
      [["b", "top"]],
    );
    const { placed, width } = layout(graph);
    const top = placed.find((entry) => entry.node.id === "top")!;
    expect(top.x).toBeCloseTo(width / 2, 5);
  });
});

describe("masteryColor", () => {
  it("is monotonic across the scale", () => {
    const swatches = [0, 0.29, 0.3, 0.49, 0.5, 0.69, 0.7, 0.84, 0.85, 1].map(masteryColor);
    // Every step is either the same swatch or the next one up; it never goes back.
    const order = ["--mastery-1", "--mastery-2", "--mastery-3", "--mastery-4", "--mastery-5"];
    const indices = swatches.map((swatch) => order.findIndex((name) => swatch.includes(name)));
    expect(indices).toEqual([...indices].sort((a, b) => a - b));
    expect(indices.every((index) => index >= 0)).toBe(true);
  });

  it("gives an unknown concept the neutral end, not the alarming one", () => {
    // A subject not studied yet is unknown, not wrong. Colouring it like a
    // failure would be a lie about the learner.
    expect(masteryColor(0)).toContain("--mastery-1");
  });
});
