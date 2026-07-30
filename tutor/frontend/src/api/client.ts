/**
 * The HTTP boundary.
 *
 * Every call the app makes lives here, so components never build a URL or parse a
 * response. Two things are worth noting.
 *
 * **Errors carry the server's message.** FastAPI returns `{"detail": "..."}` and
 * those messages are written for the learner ("the concept graph is not ready
 * yet"), so throwing them away and showing "Request failed" would discard the most
 * useful part of the response.
 *
 * **SSE is consumed with `fetch`, not `EventSource`.** `EventSource` cannot POST,
 * and both streaming endpoints need a body or have a side effect. The parser below
 * is small because the server's framing is deliberately simple: every payload is
 * one JSON `data:` line.
 */

import type {
  AnswerResult,
  AskDone,
  AskMeta,
  Changeset,
  ChangesetPreview,
  DiagnosticSession,
  DueQueue,
  Graph,
  Lesson,
  NextItem,
  NextUnit,
  Plan,
  Report,
  ReviewItem,
  ReviewResult,
  Schedule,
  StudySession,
  Subject,
  Suggestion,
  UnitCompleteResult,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");

/** An HTTP failure that kept the server's own explanation. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "Could not reach the server. It may be offline.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Pull the most useful error message out of a failed response. */
async function detailOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      const first = body.detail[0] as { msg?: string } | undefined;
      if (first?.msg) return first.msg;
    }
  } catch {
    /* fall through to the generic message */
  }
  return `Request failed (${response.status}).`;
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const patch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const api = {
  // --- subjects and graph ---
  listSubjects: () => get<Subject[]>("/subjects"),
  getSubject: (id: string) => get<Subject>(`/subjects/${id}`),
  createSubject: (name: string, description = "") =>
    post<Subject>("/subjects", { name, description }),
  getGraph: (id: string) => get<Graph>(`/subjects/${id}/graph`),
  patchCadence: (id: string, body: Record<string, unknown>) =>
    patch<Subject>(`/subjects/${id}/cadence`, body),

  // --- diagnostic ---
  startDiagnostic: (id: string, maxItems?: number) =>
    post<DiagnosticSession>(`/subjects/${id}/diagnostic`, { max_items: maxItems ?? null }),
  nextItem: (sessionId: string) => get<NextItem>(`/diagnostic/${sessionId}/next`),
  answer: (sessionId: string, itemId: string, answer: string) =>
    post<AnswerResult>(`/diagnostic/${sessionId}/answer`, { item_id: itemId, answer }),

  // --- report and plan ---
  getReport: (id: string) => get<Report>(`/subjects/${id}/report`),
  getPlan: (id: string) => get<Plan>(`/subjects/${id}/plan`),
  createPlan: (id: string, limit?: number) =>
    post<Plan>(`/subjects/${id}/plan`, { limit: limit ?? null }),
  nextUnit: (planId: string) => get<NextUnit>(`/plan/${planId}/next`),
  insertUnit: (planId: string, nodeId: string) =>
    post<Plan>(`/plan/${planId}/units`, { node_id: nodeId }),
  completeUnit: (unitId: string, answers: { item_id: string; answer: string }[], skipped = false) =>
    post<UnitCompleteResult>(`/plan/units/${unitId}/complete`, { answers, skipped }),
  getLesson: (lessonId: string) => get<Lesson>(`/lessons/${lessonId}`),

  // --- reviews ---
  getDue: (id: string) => get<DueQueue>(`/subjects/${id}/reviews`),
  nextReview: (id: string) => get<ReviewItem>(`/subjects/${id}/reviews/next`),
  answerReview: (id: string, itemId: string, answer: string) =>
    post<ReviewResult>(`/subjects/${id}/reviews/answer`, { item_id: itemId, answer }),

  // --- schedule ---
  getSchedule: (id: string) => get<Schedule>(`/subjects/${id}/schedule`),
  buildSchedule: (id: string, horizonDays = 14) =>
    post<Schedule>(`/subjects/${id}/schedule`, { horizon_days: horizonDays, persist: true }),
  completeSession: (sessionId: string, notes = "") =>
    post<StudySession>(`/sessions/${sessionId}/complete`, { notes }),

  // --- graph refinement ---
  refine: (id: string, request: string) =>
    post<Changeset>(`/subjects/${id}/graph/refine`, { request }),
  getChangeset: (changesetId: string) => get<Changeset>(`/changesets/${changesetId}`),
  previewChangeset: (changesetId: string, acceptedOpIds: string[]) =>
    get<ChangesetPreview>(
      `/changesets/${changesetId}/preview?${acceptedOpIds
        .map((opId) => `accepted_op_ids=${encodeURIComponent(opId)}`)
        .join("&")}`,
    ),
  commitChangeset: (subjectId: string, changesetId: string, acceptedOpIds: string[]) =>
    post<Changeset>(`/subjects/${subjectId}/changesets/${changesetId}`, {
      accepted_op_ids: acceptedOpIds,
    }),
  listChangesets: (id: string) => get<Changeset[]>(`/subjects/${id}/changesets`),
  listSuggestions: (id: string) => get<Suggestion[]>(`/subjects/${id}/suggestions`),
  dismissSuggestion: (suggestionId: string) =>
    post<Suggestion>(`/suggestions/${suggestionId}/dismiss`),
};

/** One parsed server-sent event. */
export interface StreamEvent {
  name: string;
  data: unknown;
}

/**
 * Consume an SSE response as an async iterable of parsed events.
 *
 * Frames are separated by a blank line and every payload is a single JSON
 * `data:` line, which is what makes this parser five lines rather than fifty.
 */
async function* readEvents(response: Response): AsyncGenerator<StreamEvent> {
  const body = response.body;
  if (!body) return;
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += value;
    let split = buffer.indexOf("\n\n");
    while (split !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const event = parseFrame(frame);
      if (event) yield event;
      split = buffer.indexOf("\n\n");
    }
  }
}

function parseFrame(frame: string): StreamEvent | null {
  let name = "";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) name = line.slice(7);
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!name) return null;
  try {
    return { name, data: data ? JSON.parse(data) : null };
  } catch {
    return null;
  }
}

/** What a streaming call reports back as it runs. */
export interface StreamHandlers {
  onMeta?: (meta: AskMeta | Record<string, unknown>) => void;
  onDelta: (text: string) => void;
  onDone?: (done: AskDone | Record<string, unknown>) => void;
  onError?: (message: string) => void;
}

async function stream(path: string, body: unknown, handlers: StreamHandlers): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    handlers.onError?.("Could not reach the server. It may be offline.");
    return;
  }
  if (!response.ok) {
    handlers.onError?.(await detailOf(response));
    return;
  }
  for await (const event of readEvents(response)) {
    if (event.name === "delta" && typeof event.data === "string") handlers.onDelta(event.data);
    else if (event.name === "meta") handlers.onMeta?.(event.data as AskMeta);
    else if (event.name === "done") handlers.onDone?.(event.data as AskDone);
    else if (event.name === "error") {
      const detail = (event.data as { detail?: string } | null)?.detail;
      handlers.onError?.(detail ?? "The stream failed.");
    }
  }
}

export const streams = {
  ask: (subjectId: string, question: string, handlers: StreamHandlers) =>
    stream(`/subjects/${subjectId}/ask`, { question }, handlers),
  lesson: (lessonId: string, handlers: StreamHandlers) =>
    stream(`/lessons/${lessonId}/stream`, {}, handlers),
};
