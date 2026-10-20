"""Deterministic knowledge chunking."""

from __future__ import annotations

import re

from memory.rag.contracts import KnowledgeChunk, KnowledgeDocument, new_chunk_id

# Prefer paragraph / sentence boundaries; avoid shredding short policy lines.
_DEFAULT_MAX_CHARS = 800
_DEFAULT_MIN_CHARS = 40


def chunk_document(
    document: KnowledgeDocument,
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
    min_chars: int = _DEFAULT_MIN_CHARS,
) -> list[KnowledgeChunk]:
    """
    Deterministic chunking.

    Short documents stay as a single chunk. Longer text splits on blank lines,
    then sentences, without breaking compact ID-like tokens when avoidable.
    """
    text = (document.content or "").strip()
    if not text:
        return []

    citation_ref = document.source_reference or document.document_id
    base_meta = {
        "document_type": str(document.document_type),
        "access_scope": str(document.access_scope),
        "title": document.title,
        "source": document.source,
    }
    if document.store_id:
        base_meta["store_id"] = document.store_id
    if document.sku:
        base_meta["sku"] = document.sku
    if document.supplier_id:
        base_meta["supplier_id"] = document.supplier_id
    if document.category:
        base_meta["category"] = document.category
    if document.policy_id:
        base_meta["policy_id"] = document.policy_id

    segments = _split_deterministic(text, max_chars=max_chars, min_chars=min_chars)
    chunks: list[KnowledgeChunk] = []
    for idx, segment in enumerate(segments):
        chunks.append(
            KnowledgeChunk(
                chunk_id=new_chunk_id(document.document_id, idx),
                document_id=document.document_id,
                chunk_index=idx,
                text=segment,
                metadata=dict(base_meta),
                source_reference=citation_ref,
                embedding_ref=None,
            )
        )
    return chunks


def _split_deterministic(text: str, *, max_chars: int, min_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    pieces: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        # Sentence-ish split; keep identifiers intact (no split on hyphens inside tokens).
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", para)
        buf = ""
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            if not buf:
                buf = sent
            elif len(buf) + 1 + len(sent) <= max_chars:
                buf = f"{buf} {sent}"
            else:
                pieces.append(buf)
                buf = sent
        if buf:
            pieces.append(buf)

    # Merge tiny trailing fragments into previous chunk when possible.
    merged: list[str] = []
    for piece in pieces:
        if merged and len(piece) < min_chars and len(merged[-1]) + 1 + len(piece) <= max_chars:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return merged or [text[:max_chars]]
