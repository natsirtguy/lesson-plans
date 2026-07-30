/**
 * The lesson reader.
 *
 * Streams the prose when it has not been written yet, and falls back to the plain
 * `GET /lessons/{id}` when it has -- which is also the request the service worker
 * caches, so a lesson read once is readable on a train.
 *
 * The offline path is the reason for the try-fetch-then-stream order: a cached
 * lesson comes back from the worker without a network round trip, and only a
 * lesson that is genuinely unwritten costs a stream.
 */

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, streams } from "../api/client";
import { Markdown } from "../components/Markdown";

export function LessonView() {
  const { lessonId = "" } = useParams();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setBody("");
    setError(null);

    void (async () => {
      try {
        const lesson = await api.getLesson(lessonId);
        if (cancelled) return;
        setTitle(lesson.title);
        if (lesson.complete && lesson.markdown) {
          setBody(lesson.markdown);
          return;
        }
      } catch (caught) {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : "Could not load the lesson.");
        return;
      }

      setStreaming(true);
      await streams.lesson(lessonId, {
        onMeta: (meta) => {
          const asRecord = meta as { title?: string };
          if (!cancelled && asRecord.title) setTitle(asRecord.title);
        },
        onDelta: (text) => {
          if (!cancelled) setBody((current) => current + text);
        },
        onError: (message) => {
          if (!cancelled) setError(message);
        },
      });
      if (!cancelled) setStreaming(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [lessonId]);

  return (
    <article className="stack">
      <div className="row">
        <button type="button" className="btn btn-quiet" onClick={() => navigate(-1)}>
          ← Back to the plan
        </button>
        {streaming && <span className="chip chip-live">writing…</span>}
      </div>

      {title && <h2 className="lesson-title">{title}</h2>}
      {error && <p className="notice notice-danger">{error}</p>}
      {body ? (
        <Markdown source={body} className="lesson" />
      ) : (
        !error && <p className="muted">Preparing the lesson…</p>
      )}
    </article>
  );
}
