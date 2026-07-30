/**
 * Lesson prose, rendered.
 *
 * The renderer itself -- marked, KaTeX, highlight.js, and KaTeX's fonts -- is most
 * of this app's JavaScript and is needed by exactly two views. It is therefore
 * loaded on demand rather than up front, so the graph, report, plan and schedule
 * all open without paying for it.
 *
 * Until it arrives the raw markdown is shown as preformatted text. That matters
 * more than it looks: prose *streams*, so the first chunks land before the module
 * has finished loading, and showing nothing would make a fast answer look like a
 * hung one. Unstyled text that becomes styled text is a better failure than a
 * blank panel.
 */

import { useEffect, useMemo, useState } from "react";

type Renderer = (source: string) => string;

let cached: Renderer | null = null;
let pending: Promise<Renderer> | null = null;

/** Load the heavy renderer once per session, sharing the in-flight promise. */
function loadRenderer(): Promise<Renderer> {
  if (cached) return Promise.resolve(cached);
  pending ??= import("./markdown-render").then((module) => {
    cached = module.renderMarkdown;
    return cached;
  });
  return pending;
}

export interface MarkdownProps {
  source: string;
  className?: string;
}

export function Markdown({ source, className }: MarkdownProps) {
  const [renderer, setRenderer] = useState<Renderer | null>(cached);

  useEffect(() => {
    if (renderer) return;
    let cancelled = false;
    void loadRenderer().then((loaded) => {
      if (!cancelled) setRenderer(() => loaded);
    });
    return () => {
      cancelled = true;
    };
  }, [renderer]);

  const html = useMemo(
    () => (renderer ? renderer(source) : null),
    [renderer, source],
  );

  const classes = className ? `prose ${className}` : "prose";
  if (html === null) {
    return <pre className={`${classes} prose-raw`}>{source}</pre>;
  }
  return (
    <div
      className={classes}
      // The only source of this HTML is our own backend, and the alternative --
      // a full sanitiser -- is a large dependency for a single-user local app.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
