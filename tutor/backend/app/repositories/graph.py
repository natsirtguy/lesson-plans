"""Persistence for concept nodes, prerequisite edges, and mastery records.

Nodes and edges are soft-deleted rather than removed, so "the live graph" always
means "rows with ``deleted_at IS NULL``". Every read here applies that filter; a
query that forgets it will resurrect removed concepts.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import utcnow
from app.models.graph import ConceptEdge, ConceptNode, MasteryRecord

_PUNCTUATION = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE = re.compile(r"\s+")


def name_key(name: str) -> str:
    """Normalize a concept name into a stable identity key.

    This is what lets a removed concept be recognised when it is re-added, so the
    learner's history comes back with it. Accents are folded, punctuation dropped,
    case and spacing normalized -- "Bayes' Theorem" and "bayes theorem" are the
    same concept.

    :param name: The concept name as written.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stripped = _PUNCTUATION.sub(" ", folded.lower())
    return _WHITESPACE.sub(" ", stripped).strip()


class GraphRepository:
    """Reads and writes the graph and its mastery records."""

    def __init__(self, session: AsyncSession) -> None:
        """
        :param session: The active database session.
        """
        self._session = session

    # --- nodes ---------------------------------------------------------------

    async def live_nodes(self, subject_id: str) -> list[ConceptNode]:
        """Fetch every concept still in the graph.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(ConceptNode)
            .where(
                ConceptNode.subject_id == subject_id,
                ConceptNode.deleted_at.is_(None),
            )
            .order_by(ConceptNode.tier, ConceptNode.name)
        )
        return list(result.scalars())

    async def all_nodes(self, subject_id: str) -> list[ConceptNode]:
        """Fetch every concept including soft-deleted ones.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(ConceptNode)
            .where(ConceptNode.subject_id == subject_id)
            .order_by(ConceptNode.tier, ConceptNode.name)
        )
        return list(result.scalars())

    async def get_node(self, node_id: str) -> ConceptNode | None:
        """Fetch one concept by id, live or not.

        :param node_id: The concept's id.
        """
        return await self._session.get(ConceptNode, node_id)

    async def find_by_key(self, subject_id: str, key: str) -> ConceptNode | None:
        """Find a concept by its normalized name, live or soft-deleted.

        :param subject_id: The subject to search.
        :param key: A key from :func:`name_key`.
        """
        result = await self._session.execute(
            select(ConceptNode).where(
                ConceptNode.subject_id == subject_id, ConceptNode.name_key == key
            )
        )
        return result.scalars().first()

    def add_node(self, node: ConceptNode) -> ConceptNode:
        """Stage a new concept for insertion.

        :param node: The concept to add.
        """
        self._session.add(node)
        return node

    def soft_delete_node(self, node: ConceptNode, *, version: int) -> None:
        """Remove a concept from the live graph, keeping its row and history.

        :param node: The concept to remove.
        :param version: The graph version the removal belongs to.
        """
        node.deleted_at = utcnow()
        node.removed_in_version = version

    def restore_node(self, node: ConceptNode, *, version: int) -> None:
        """Return a previously removed concept to the live graph.

        Its mastery record was never deleted, so the learner's history comes back
        with it.

        :param node: The concept to restore.
        :param version: The graph version the restoration belongs to.
        """
        node.deleted_at = None
        node.removed_in_version = None
        node.introduced_in_version = version
        node.superseded_by = None

    # --- edges ---------------------------------------------------------------

    async def live_edges(self, subject_id: str) -> list[ConceptEdge]:
        """Fetch every prerequisite relation still in the graph.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(ConceptEdge).where(
                ConceptEdge.subject_id == subject_id,
                ConceptEdge.deleted_at.is_(None),
            )
        )
        return list(result.scalars())

    async def find_edge(self, subject_id: str, prereq_id: str, node_id: str) -> ConceptEdge | None:
        """Find one prerequisite relation, live or soft-deleted.

        :param subject_id: The subject to search.
        :param prereq_id: The prerequisite concept.
        :param node_id: The dependent concept.
        """
        result = await self._session.execute(
            select(ConceptEdge).where(
                ConceptEdge.subject_id == subject_id,
                ConceptEdge.prereq_id == prereq_id,
                ConceptEdge.node_id == node_id,
            )
        )
        return result.scalars().first()

    async def add_edge(
        self, subject_id: str, prereq_id: str, node_id: str, *, version: int
    ) -> ConceptEdge:
        """Add a prerequisite relation, reviving a soft-deleted one if present.

        Reviving rather than inserting keeps the unique constraint satisfiable
        after an edge is removed and later restored.

        :param subject_id: The subject being changed.
        :param prereq_id: The prerequisite concept.
        :param node_id: The dependent concept.
        :param version: The graph version this belongs to.
        """
        existing = await self.find_edge(subject_id, prereq_id, node_id)
        if existing is not None:
            existing.deleted_at = None
            existing.removed_in_version = None
            existing.introduced_in_version = version
            return existing
        edge = ConceptEdge(
            subject_id=subject_id,
            prereq_id=prereq_id,
            node_id=node_id,
            introduced_in_version=version,
        )
        self._session.add(edge)
        return edge

    def soft_delete_edge(self, edge: ConceptEdge, *, version: int) -> None:
        """Remove a prerequisite relation from the live graph.

        :param edge: The relation to remove.
        :param version: The graph version the removal belongs to.
        """
        edge.deleted_at = utcnow()
        edge.removed_in_version = version

    # --- mastery -------------------------------------------------------------

    async def mastery_records(self, subject_id: str) -> list[MasteryRecord]:
        """Fetch every mastery record for a subject, including removed concepts'.

        :param subject_id: The subject to read.
        """
        result = await self._session.execute(
            select(MasteryRecord).where(MasteryRecord.subject_id == subject_id)
        )
        return list(result.scalars())

    async def mastery_for(self, node_id: str) -> MasteryRecord | None:
        """Fetch one concept's mastery record.

        :param node_id: The concept's id.
        """
        result = await self._session.execute(
            select(MasteryRecord).where(MasteryRecord.node_id == node_id)
        )
        return result.scalars().first()

    def add_mastery(self, record: MasteryRecord) -> MasteryRecord:
        """Stage a new mastery record for insertion.

        :param record: The record to add.
        """
        self._session.add(record)
        return record
