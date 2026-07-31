/**
 * Mirrors of the backend's Pydantic response schemas.
 *
 * Hand-written rather than generated from the OpenAPI document. The API is small
 * and stable, a generator would be another build step in a project that has none,
 * and hand-writing them means the client only declares the fields it actually
 * reads -- which makes an unused field on the backend visible rather than silently
 * carried along.
 */

export interface Subject {
  id: string;
  name: string;
  description: string;
  graph_version: number;
  graph_status: "pending" | "generating" | "ready" | "failed";
  graph_error: string | null;
  days_per_week: number;
  minutes_per_session: number;
  daily_review_cap: number;
  deadline: string | null;
  target_retention: number;
  recovery_aware: boolean;
  created_at: string;
  node_count: number;
}

export interface GraphNode {
  id: string;
  name: string;
  definition: string;
  tier: number;
  mastery: number;
  confidence: number;
  unblocks: number;
  /** True when every prerequisite is unmastered, so nothing currently reaches it. */
  locked: boolean;
  ready: boolean;
}

export interface GraphEdge {
  prereq_id: string;
  node_id: string;
  /** True when the prerequisite is not yet mastered, so the edge is not crossable. */
  locked: boolean;
}

export interface Graph {
  subject_id: string;
  graph_version: number;
  graph_status: Subject["graph_status"];
  nodes: GraphNode[];
  edges: GraphEdge[];
  coverage: number;
}

export interface NodeScore {
  node_id: string;
  name: string;
  tier: number;
  mastery: number;
  confidence: number;
  unblocks: number;
}

export interface TierSummary {
  tier: number;
  count: number;
  mean_mastery: number;
  mean_confidence: number;
  mastered: number;
}

export interface Calibration {
  success_rate: number | null;
  sample_size: number;
  verdict: "widen" | "tighten" | "on_target" | "insufficient_data";
  advice: string;
}

export interface Report {
  subject_id: string;
  subject_name: string;
  graph_version: number;
  coverage: number;
  mean_confidence: number;
  total_nodes: number;
  mastered_nodes: number;
  unassessed_nodes: number;
  tiers: TierSummary[];
  strengths: NodeScore[];
  weaknesses: NodeScore[];
  blocking: { target_tier: number | null; blocked: NodeScore[]; blockers: NodeScore[] };
  calibration: Calibration;
  ready_to_learn: NodeScore[];
  open_suggestions: number;
  has_plan: boolean;
  diagnostic_responses: number;
}

export interface DiagnosticSession {
  id: string;
  subject_id: string;
  status: string;
  asked_count: number;
  max_items: number;
  min_items: number;
  mean_confidence: number;
  stop_reason: string | null;
}

export interface Item {
  id: string;
  node_id: string;
  node_name: string;
  tier: number;
  item_format: "multiple_choice" | "short_free_text" | "explain_why_wrong";
  difficulty: number;
  stem: string;
  choices: string[];
  asked_count: number;
  max_items: number;
}

export interface NextItem {
  item: Item | null;
  finished: boolean;
  stop_reason: string | null;
  session: DiagnosticSession;
}

export interface MasteryChange {
  node_id: string;
  node_name: string;
  mastery_before: number;
  mastery_after: number;
  confidence_after: number;
  propagated: boolean;
}

export interface AnswerResult {
  correct: boolean;
  score: number;
  feedback: string;
  misconception: string | null;
  answer_key: string;
  changes: MasteryChange[];
  session: DiagnosticSession;
}

export interface PlanUnit {
  id: string;
  seq: number;
  node_id: string;
  node_name: string;
  tier: number;
  title: string;
  objective: string;
  estimated_minutes: number;
  status: "pending" | "in_progress" | "complete" | "skipped";
  placement_reason: string;
  priority: number;
  interleaved_node_ids: string[];
  interleaved_names: string[];
  first_acquisition: boolean;
  completed_at: string | null;
}

export interface Plan {
  id: string;
  subject_id: string;
  status: string;
  graph_version: number;
  coverage_at_creation: number;
  coverage_now: number;
  created_at: string;
  units: PlanUnit[];
  skipped_mastered: number;
  truncated: number;
}

export interface ExitCheckItem {
  id: string;
  node_id: string;
  node_name: string;
  tier: number;
  item_format: Item["item_format"];
  difficulty: number;
  stem: string;
  choices: string[];
}

export interface NextUnit {
  unit: PlanUnit | null;
  finished: boolean;
  exit_check: ExitCheckItem[];
  lesson_id: string | null;
}

export interface UnitCompleteResult {
  unit_id: string;
  status: string;
  exit_score: number | null;
  mastery_before: number;
  mastery_after: number;
  feedback: string[];
  coverage_now: number;
  next_unit_id: string | null;
}

export interface Lesson {
  id: string;
  subject_id: string;
  node_id: string | null;
  unit_id: string | null;
  title: string;
  difficulty: number;
  level: string;
  markdown: string;
  complete: boolean;
  created_at: string;
}

export interface ReviewCard {
  node_id: string;
  node_name: string;
  tier: number;
  state: string;
  stability: number;
  difficulty: number;
  due_at: string | null;
  last_review_at: string | null;
  reps: number;
  lapses: number;
  overdue_days: number;
  retrievability: number;
  mastery: number;
  unblocks: number;
}

export interface DueQueue {
  subject_id: string;
  due: ReviewCard[];
  deferred: number;
  daily_cap: number;
  total_cards: number;
  upcoming: ReviewCard[];
}

export interface ReviewItem {
  id: string;
  node_id: string;
  node_name: string;
  tier: number;
  item_format: Item["item_format"];
  difficulty: number;
  stem: string;
  choices: string[];
  remaining: number;
}

export interface ReviewResult {
  correct: boolean;
  score: number;
  grade: number;
  feedback: string;
  misconception: string | null;
  answer_key: string;
  changes: MasteryChange[];
  card: ReviewCard;
  interval_days: number;
  schedule_reason: string;
  remaining: number;
}

export interface StudySession {
  id: string | null;
  scheduled_for: string;
  status: "planned" | "complete" | "missed";
  planned_minutes: number;
  retrieval_minutes: number;
  review_node_ids: string[];
  review_names: string[];
  new_node_ids: string[];
  new_names: string[];
  unit_ids: string[];
  deferred_node_ids: string[];
  notes: string;
  completed_at: string | null;
}

export interface Schedule {
  subject_id: string;
  generated_for: string;
  horizon_days: number;
  days_per_week: number;
  minutes_per_session: number;
  daily_review_cap: number;
  sessions: StudySession[];
  deadline: {
    deadline: string | null;
    sessions_available: number;
    sessions_needed: number;
    achievable: boolean;
    shortfall_sessions: number;
    message: string;
  };
  adherence: {
    sessions_planned: number;
    sessions_completed: number;
    sessions_missed: number;
    completion_rate: number | null;
    current_streak: number;
    longest_streak: number;
  };
  units_scheduled: number;
  units_remaining: number;
  due_now: number;
}

export interface ChangesetOp {
  id: string;
  seq: number;
  op_type: string;
  rationale: string;
  summary: string;
  accepted: boolean;
  payload: Record<string, unknown>;
}

export interface Changeset {
  id: string;
  subject_id: string;
  status: "proposed" | "committed" | "rejected" | "invalid";
  request: string;
  rationale: string;
  graph_version_before: number;
  graph_version_after: number | null;
  validation_error: string | null;
  created_at: string;
  operations: ChangesetOp[];
}

export interface ChangesetPreview {
  changeset_id: string;
  valid: boolean;
  error: string | null;
  summary: string[];
  added_names: string[];
  removed_names: string[];
  renamed: string[];
  retiered: string[];
  edges_changed: number;
  affected_node_ids: string[];
}

export interface Suggestion {
  id: string;
  kind: string;
  summary: string;
  node_id: string | null;
  status: string;
  created_at: string;
}

/** The `meta` frame of an ask stream. */
export interface AskMeta {
  question: string;
  kind: string;
  resolved_kind: "existing_node" | "new_node" | "off_subject";
  title: string;
  node_id: string | null;
  node_name: string | null;
  reason: string;
  lesson_id: string;
  cached: boolean;
  graph_version: number;
}

/** The `done` frame of an ask stream. */
export interface AskDone {
  lesson_id: string;
  complete: boolean;
  characters: number;
  offer: {
    kind: "insert_unit" | "review_suggestion" | "already_planned" | "none";
    node_id: string | null;
    suggestion_id: string | null;
    message: string;
  };
}
