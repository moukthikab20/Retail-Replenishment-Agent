"""Local vector store — SQL metadata + in-process vectors (future: pgvector/etc.)."""

from __future__ import annotations

import json
import math
import threading
from typing import Any

from sqlalchemy import select

from database.connection import get_session, init_db
from database.models import KnowledgeChunkRow


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class LocalVectorStore:
    """
    Lightweight local vector index.

    Vectors are kept in-process and mirrored to knowledge_chunks.embedding_json
    for durability across sessions in the same DB.
    """

    store_name = "local"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._vectors: dict[str, list[float]] = {}
        self._payloads: dict[str, dict[str, Any]] = {}

    def upsert(
        self,
        *,
        chunk_ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        if not (len(chunk_ids) == len(vectors) == len(payloads)):
            raise ValueError("chunk_ids, vectors, and payloads must align")
        init_db()
        with self._lock:
            for chunk_id, vector, payload in zip(chunk_ids, vectors, payloads):
                self._vectors[chunk_id] = list(vector)
                self._payloads[chunk_id] = dict(payload)
            with get_session() as session:
                for chunk_id, vector in zip(chunk_ids, vectors):
                    row = session.get(KnowledgeChunkRow, chunk_id)
                    if row is not None:
                        row.embedding_ref = f"local:{chunk_id}"
                        row.embedding_json = json.dumps(vector)
                session.flush()

    def delete_document(self, document_id: str) -> int:
        init_db()
        removed = 0
        with self._lock:
            to_delete = [
                cid
                for cid, payload in self._payloads.items()
                if payload.get("document_id") == document_id
            ]
            for cid in to_delete:
                self._vectors.pop(cid, None)
                self._payloads.pop(cid, None)
                removed += 1
            with get_session() as session:
                rows = list(
                    session.scalars(
                        select(KnowledgeChunkRow).where(
                            KnowledgeChunkRow.document_id == document_id
                        )
                    )
                )
                for row in rows:
                    if row.chunk_id in self._vectors:
                        self._vectors.pop(row.chunk_id, None)
                        self._payloads.pop(row.chunk_id, None)
                        removed += 1
                    row.embedding_json = None
                    row.embedding_ref = None
                session.flush()
        return removed

    def search(
        self,
        vector: list[float],
        *,
        limit: int = 5,
        filters: dict[str, Any] | None = None,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        self._ensure_loaded()
        filters = filters or {}
        scored: list[tuple[float, str]] = []
        with self._lock:
            for chunk_id, stored in self._vectors.items():
                payload = self._payloads.get(chunk_id) or {}
                if not self._matches(payload, filters):
                    continue
                score = _cosine(vector, stored)
                if score >= float(min_score):
                    scored.append((score, chunk_id))
        scored.sort(key=lambda item: item[0], reverse=True)
        out: list[dict[str, Any]] = []
        for score, chunk_id in scored[: max(1, int(limit))]:
            payload = dict(self._payloads.get(chunk_id) or {})
            out.append(
                {
                    "chunk_id": chunk_id,
                    "score": score,
                    "payload": payload,
                }
            )
        return out

    def _matches(self, payload: dict[str, Any], filters: dict[str, Any]) -> bool:
        scopes = filters.get("allowed_scopes")
        if scopes is not None:
            if payload.get("access_scope") not in set(scopes):
                return False
        for key in ("document_type", "store_id", "sku", "supplier_id", "document_id"):
            if key in filters and filters[key] is not None:
                if payload.get(key) != filters[key]:
                    return False
        return True

    def _ensure_loaded(self) -> None:
        if self._vectors:
            return
        init_db()
        with get_session() as session:
            rows = list(session.scalars(select(KnowledgeChunkRow)))
            with self._lock:
                for row in rows:
                    if not row.embedding_json:
                        continue
                    try:
                        vec = json.loads(row.embedding_json)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(vec, list):
                        continue
                    self._vectors[row.chunk_id] = [float(x) for x in vec]
                    self._payloads[row.chunk_id] = {
                        "document_id": row.document_id,
                        "chunk_index": row.chunk_index,
                        "text": row.text,
                        "source_reference": row.source_reference,
                        "access_scope": row.access_scope,
                        "document_type": row.document_type,
                        "title": row.title,
                        "source": row.source,
                        "store_id": row.store_id,
                        "sku": row.sku,
                        "supplier_id": row.supplier_id,
                        "citation": (
                            f"[{(row.document_type or 'knowledge').replace('_', ' ').title()} "
                            f"{row.source_reference or row.document_id}]"
                        ),
                    }

    def health_check(self) -> dict[str, Any]:
        try:
            self._ensure_loaded()
            with self._lock:
                count = len(self._vectors)
            return {
                "ok": True,
                "store": self.store_name,
                "vector_count": count,
                "vector_enabled": True,
                "status": "healthy",
                "message": "Local vector store ready (in-process + SQL mirror).",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "store": self.store_name,
                "status": "unavailable",
                "message": f"Vector store unavailable: {type(exc).__name__}",
            }


_store: LocalVectorStore | None = None


def get_vector_store(*, force_new: bool = False) -> LocalVectorStore:
    global _store
    if _store is None or force_new:
        _store = LocalVectorStore()
    return _store


def reset_vector_store() -> None:
    global _store
    _store = None
