/**
 * Routing and the shared shell.
 *
 * Every subject view lives under `/subjects/:id/*` and shares a header with the
 * subject's name, its coverage, and the tab strip. The ask bar is mounted once by
 * the layout rather than by each view, so it is genuinely always reachable.
 */

import { Suspense } from "react";
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Route,
  Routes,
  useParams,
} from "react-router-dom";

import { AskPalette } from "./components/AskPalette";
import { useSubject } from "./hooks";
import { ChangesetsView } from "./views/ChangesetsView";
import { DiagnosticView } from "./views/DiagnosticView";
import { GraphPage } from "./views/GraphPage";
import { LessonView } from "./views/LessonView";
import { PlanView } from "./views/PlanView";
import { ReportView } from "./views/ReportView";
import { ReviewView } from "./views/ReviewView";
import { ScheduleView } from "./views/ScheduleView";
import { SubjectsView } from "./views/SubjectsView";

const TABS = [
  { to: "graph", label: "Graph" },
  { to: "report", label: "Report" },
  { to: "plan", label: "Plan" },
  { to: "review", label: "Review" },
  { to: "schedule", label: "Schedule" },
  { to: "changes", label: "Changes" },
] as const;

function SubjectLayout() {
  const { subjectId = "" } = useParams();
  const { subject, reload } = useSubject(subjectId);

  return (
    <div className="shell">
      <header className="shell-header">
        <div className="shell-title">
          <NavLink to="/" className="back" aria-label="All subjects">
            ←
          </NavLink>
          <h1>{subject?.name ?? "…"}</h1>
          {subject && subject.graph_status !== "ready" && (
            <span className="chip chip-warn">{subject.graph_status}</span>
          )}
        </div>
        <nav className="tabs" aria-label="Subject sections">
          {TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              className={({ isActive }) => (isActive ? "tab is-active" : "tab")}
            >
              {tab.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="shell-main">
        <Suspense fallback={<p className="muted">Loading…</p>}>
          <Routes>
            <Route index element={<Navigate to="graph" replace />} />
            <Route path="graph" element={<GraphPage subjectId={subjectId} />} />
            <Route path="report" element={<ReportView subjectId={subjectId} />} />
            <Route path="diagnostic" element={<DiagnosticView subjectId={subjectId} />} />
            <Route path="plan" element={<PlanView subjectId={subjectId} />} />
            <Route path="plan/lesson/:lessonId" element={<LessonView />} />
            <Route path="review" element={<ReviewView subjectId={subjectId} />} />
            <Route path="schedule" element={<ScheduleView subjectId={subjectId} />} />
            <Route path="changes" element={<ChangesetsView subjectId={subjectId} />} />
          </Routes>
        </Suspense>
      </main>

      <footer className="shell-footer">
        <AskPalette subjectId={subjectId} onChanged={reload} />
      </footer>
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<SubjectsView />} />
        <Route path="/subjects/:subjectId/*" element={<SubjectLayout />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
