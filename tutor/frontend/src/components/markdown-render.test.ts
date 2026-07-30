/**
 * Tests for the maths-extraction pass.
 *
 * This exists because of one specific ordering bug: markdown run *before* LaTeX is
 * pulled out turns `$x_i$ and $y_i$` into emphasis, silently, and the lesson
 * renders with a stray italic run instead of two variables. Every case here is a
 * construct that markdown would damage if the order were wrong.
 */

import { describe, expect, it } from "vitest";
import { extractMath, renderMarkdown } from "./markdown-render";

describe("extractMath", () => {
  it("pulls inline mathematics out before markdown can see it", () => {
    const { text, math } = extractMath("The relation $y = f(x)$ holds.");
    expect(math).toHaveLength(1);
    expect(text).not.toContain("$");
  });

  it("protects subscripts from being read as emphasis", () => {
    // Two underscores across two expressions is exactly what markdown turns into
    // an italic run.
    const { math } = extractMath("Compare $x_i$ with $y_i$.");
    expect(math).toHaveLength(2);
  });

  it("handles display mathematics", () => {
    const { text, math } = extractMath("Before\n\n$$\\int_0^1 x\\,dx$$\n\nAfter");
    expect(math).toHaveLength(1);
    expect(text).toContain("Before");
    expect(text).toContain("After");
  });

  it("leaves a dollar sign inside a fenced code block alone", () => {
    // A shell prompt is not mathematics, and treating it as such swallows the
    // whole block.
    const source = "```bash\n$ echo hi\n$ echo bye\n```";
    const { math } = extractMath(source);
    expect(math).toHaveLength(0);
  });

  it("leaves a dollar sign inside inline code alone", () => {
    const { math } = extractMath("Use `$HOME` and `$PATH` for paths.");
    expect(math).toHaveLength(0);
  });

  it("restores fenced code exactly as it was", () => {
    const source = "```python\ndef f(x):\n    return x * 2\n```";
    const { text } = extractMath(source);
    expect(text).toBe(source);
  });

  it("ignores a lone dollar sign", () => {
    const { math } = extractMath("It costs $5 to enter.");
    expect(math).toHaveLength(0);
  });

  it("does not treat an escaped dollar as a delimiter", () => {
    const { math } = extractMath("A literal \\$ sign, and another \\$ sign.");
    expect(math).toHaveLength(0);
  });
});

describe("renderMarkdown", () => {
  it("renders headings and paragraphs", () => {
    const html = renderMarkdown("## Objective\n\nDo the thing.");
    expect(html).toContain("<h2");
    expect(html).toContain("Do the thing.");
  });

  it("renders mathematics through KaTeX rather than as literal dollars", () => {
    const html = renderMarkdown("The relation $y = f(x)$ holds.");
    expect(html).toContain("katex");
    expect(html).not.toContain("$y = f(x)$");
  });

  it("keeps subscripted variables distinct instead of italicising between them", () => {
    const html = renderMarkdown("Compare $x_i$ with $y_i$.");
    expect(html).toContain("katex");
    // The bug this guards: markdown turning `_i$ with $y_` into one <em>.
    expect(html).not.toContain("<em>");
  });

  it("highlights a fenced code block with a known language", () => {
    const html = renderMarkdown("```python\ndef f():\n    return 1\n```");
    expect(html).toContain("hljs");
    expect(html).toContain("language-python");
  });

  it("renders an unknown language as escaped plain code", () => {
    const html = renderMarkdown("```notalanguage\n<script>alert(1)</script>\n```");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>alert");
  });

  it("shows malformed mathematics as source instead of failing the lesson", () => {
    const html = renderMarkdown("Broken: $\\frac{1}{$ and then more prose.");
    expect(html).toContain("more prose");
  });

  it("renders an empty document without throwing", () => {
    expect(renderMarkdown("")).toBe("");
  });

  it("renders a whole lesson end to end", () => {
    const lesson = [
      "## Objective",
      "",
      "Explain it.",
      "",
      "## Explanation",
      "",
      "The relation is $y = f(x)$, and in display form:",
      "",
      "$$E = mc^2$$",
      "",
      "```python",
      "x = 1",
      "```",
      "",
      "## Practice",
      "",
      "1. First",
      "2. Second",
    ].join("\n");
    const html = renderMarkdown(lesson);

    expect(html).toContain("<h2");
    expect(html).toContain("katex");
    expect(html).toContain("language-python");
    expect(html).toContain("<ol");
    expect(html).not.toContain("MATH");
  });
});
