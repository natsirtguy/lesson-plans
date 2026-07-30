/**
 * Tests for the SSE parser.
 *
 * The failure mode worth guarding is the one that only shows up on a real
 * network: chunk boundaries have nothing to do with frame boundaries, so an event
 * routinely arrives split in half and a single read routinely carries several.
 * A parser that assumes one chunk is one frame passes every hand-written test and
 * drops content in production.
 */

import { describe, expect, it } from "vitest";
import { createEventParser } from "./client";

function frame(name: string, data: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

describe("createEventParser", () => {
  it("parses one whole frame", () => {
    const parse = createEventParser();
    expect(parse(frame("delta", "hello"))).toEqual([{ name: "delta", data: "hello" }]);
  });

  it("parses several frames arriving in one chunk", () => {
    const parse = createEventParser();
    const events = parse(frame("meta", { a: 1 }) + frame("delta", "x") + frame("done", { b: 2 }));
    expect(events.map((event) => event.name)).toEqual(["meta", "delta", "done"]);
  });

  it("reassembles a frame split across chunks", () => {
    const parse = createEventParser();
    const whole = frame("delta", "a complete sentence");
    const cut = Math.floor(whole.length / 2);

    expect(parse(whole.slice(0, cut))).toEqual([]);
    expect(parse(whole.slice(cut))).toEqual([{ name: "delta", data: "a complete sentence" }]);
  });

  it("survives being fed one character at a time", () => {
    const parse = createEventParser();
    const payload = frame("meta", { lesson_id: "abc" }) + frame("delta", "text");
    const events = [...payload].flatMap((character) => parse(character));

    expect(events).toEqual([
      { name: "meta", data: { lesson_id: "abc" } },
      { name: "delta", data: "text" },
    ]);
  });

  it("keeps a trailing partial frame buffered rather than emitting it", () => {
    const parse = createEventParser();
    expect(parse(frame("delta", "one") + "event: delta\ndata: \"tw")).toEqual([
      { name: "delta", data: "one" },
    ]);
    expect(parse('o"\n\n')).toEqual([{ name: "delta", data: "two" }]);
  });

  it("preserves newlines inside a delta", () => {
    // The whole reason payloads are JSON: a raw markdown delta would split into
    // two frames at every blank line.
    const parse = createEventParser();
    const markdown = "## Heading\n\nA paragraph.\n\n```py\nx = 1\n```\n";
    expect(parse(frame("delta", markdown))).toEqual([{ name: "delta", data: markdown }]);
  });

  it("skips a frame whose payload is not valid JSON", () => {
    const parse = createEventParser();
    expect(parse("event: delta\ndata: {not json\n\n" + frame("done", null))).toEqual([
      { name: "done", data: null },
    ]);
  });

  it("ignores a frame with no event name", () => {
    const parse = createEventParser();
    expect(parse(': a comment\n\n' + frame("delta", "x"))).toEqual([
      { name: "delta", data: "x" },
    ]);
  });
});
