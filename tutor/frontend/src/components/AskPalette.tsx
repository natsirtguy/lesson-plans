/**
 * The always-reachable ask box.
 *
 * Cmd+K (or Ctrl+K) from anywhere, plus a persistent bar at the bottom of every
 * subject view so it is reachable by thumb on a phone -- a keyboard shortcut is
 * not an affordance on the device this app is mostly used on.
 *
 * The answer streams into the panel as it arrives. When the question turns out to
 * be about something the graph is missing, or about a concept the plan has not
 * scheduled, the offer that comes back on the `done` frame is shown as a single
 * action the learner can take or ignore. Nothing is applied automatically: an
 * offer is the whole mechanism by which a stray question is prevented from
 * rewriting the graph.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, streams } from "../api/client";
import type { AskDone, AskMeta } from "../api/types";
import { Markdown } from "./Markdown";

export interface AskPaletteProps {
  subjectId: string;
  /** Called after an offer is accepted, so the caller can refresh what it shows. */
  onChanged?: () => void;
}

export function AskPalette({ subjectId, onChanged }: AskPaletteProps) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [meta, setMeta] = useState<AskMeta | null>(null);
  const [body, setBody] = useState("");
  const [done, setDone] = useState<AskDone | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const ask = useCallback(async () => {
    const asked = question.trim();
    if (!asked || busy) return;
    setBusy(true);
    setBody("");
    setMeta(null);
    setDone(null);
    setError(null);
    setAccepted(null);
    await streams.ask(subjectId, asked, {
      onMeta: (payload) => setMeta(payload as AskMeta),
      onDelta: (text) => setBody((current) => current + text),
      onDone: (payload) => setDone(payload as AskDone),
      onError: setError,
    });
    setBusy(false);
  }, [busy, question, subjectId]);

  const acceptOffer = useCallback(async () => {
    if (!done || done.offer.kind !== "insert_unit" || !done.offer.node_id) return;
    try {
      const plan = await api.getPlan(subjectId);
      await api.insertUnit(plan.id, done.offer.node_id);
      setAccepted("Added to your plan.");
      onChanged?.();
    } catch (caught) {
      setAccepted(caught instanceof Error ? caught.message : "Could not add it to the plan.");
    }
  }, [done, onChanged, subjectId]);

  return (
    <>
      <button
        type="button"
        className="ask-bar"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
      >
        <span>Ask anything about this subject…</span>
        <kbd>⌘K</kbd>
      </button>

      {open && (
        <div className="overlay" role="dialog" aria-modal="true" aria-label="Ask anything">
          <button
            type="button"
            className="overlay-scrim"
            aria-label="Close"
            onClick={() => setOpen(false)}
          />
          <div className="palette">
            <form
              className="palette-input"
              onSubmit={(event) => {
                event.preventDefault();
                void ask();
              }}
            >
              <input
                ref={inputRef}
                type="text"
                value={question}
                placeholder="Why does this actually work?"
                onChange={(event) => setQuestion(event.target.value)}
                aria-label="Your question"
              />
              <button type="submit" className="btn btn-accent" disabled={busy || !question.trim()}>
                {busy ? "Answering…" : "Ask"}
              </button>
            </form>

            {error && <p className="notice notice-danger">{error}</p>}

            {meta && (
              <p className="palette-meta">
                <Classification kind={meta.resolved_kind} name={meta.node_name} />
                {meta.cached && <span className="chip">from cache</span>}
              </p>
            )}

            {body && (
              <div className="palette-body">
                <Markdown source={body} />
              </div>
            )}

            {done && done.offer.kind !== "none" && (
              <div className="offer">
                <p>{done.offer.message}</p>
                {done.offer.kind === "insert_unit" && !accepted && (
                  <button type="button" className="btn" onClick={() => void acceptOffer()}>
                    Add it to my plan
                  </button>
                )}
                {accepted && <p className="muted">{accepted}</p>}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function Classification({ kind, name }: { kind: string; name: string | null }) {
  if (kind === "existing_node" && name) {
    return (
      <>
        About <strong>{name}</strong>, which is already in your graph.
      </>
    );
  }
  if (kind === "new_node") {
    return <>Part of this subject, but missing from your graph.</>;
  }
  return <>Outside this subject — answered without touching your graph.</>;
}
