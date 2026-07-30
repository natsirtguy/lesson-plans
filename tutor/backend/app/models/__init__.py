"""ORM models.

Every model is imported here so that ``Base.metadata`` is fully populated by the
time Alembic or the test harness inspects it.
"""

from __future__ import annotations

from app.models.assessment import DiagnosticSession, ItemResponse, QuizItem
from app.models.changeset import Changeset, ChangesetOp, GraphSuggestion
from app.models.graph import ConceptEdge, ConceptNode, MasteryRecord
from app.models.plan import Lesson, LessonPlan, PlanUnit
from app.models.scheduling import ReviewCard, StudySession
from app.models.subject import Subject

__all__ = [
    "Changeset",
    "ChangesetOp",
    "ConceptEdge",
    "ConceptNode",
    "DiagnosticSession",
    "GraphSuggestion",
    "ItemResponse",
    "Lesson",
    "LessonPlan",
    "MasteryRecord",
    "PlanUnit",
    "QuizItem",
    "ReviewCard",
    "StudySession",
    "Subject",
]
