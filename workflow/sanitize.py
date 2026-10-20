"""Sanitize step/tool outputs — strip secrets and chain-of-thought."""

from __future__ import annotations

from typing import Any

_SECRET_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth_token",
    "session_secret",
    "credential",
    "credentials",
    "private_key",
    "access_code",
    "openai_api_key",
    "chain_of_thought",
    "reasoning",
    "scratchpad",
}


def sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lk = str(key).lower()
            if lk in _SECRET_KEYS or any(s in lk for s in ("password", "secret", "token", "api_key")):
                out[str(key)] = "[redacted]"
            else:
                out[str(key)] = sanitize_value(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [sanitize_value(v, depth=depth + 1) for v in value[:50]]
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "…"
    return value


def summarize_output(output: dict[str, Any] | None) -> dict[str, Any]:
    data = sanitize_value(dict(output or {}))
    if not isinstance(data, dict):
        return {"result": data}
    # Keep compact summary keys preferred for ops.
    preferred = (
        "resolved",
        "decision",
        "require_human",
        "tool",
        "status",
        "recommendation_id",
        "approval_id",
        "order_intent_id",
        "purchase_order_id",
        "external_order_id",
        "error",
        "degraded",
        "waiting",
        "finished",
        "decision_ops",
        "llm_ops",
        "memory_retrieved",
    )
    summary = {k: data[k] for k in preferred if k in data}
    if not summary:
        # Fall back to shallow copy without large nested blobs.
        for k, v in list(data.items())[:12]:
            if k in {"raw", "messages", "prompt", "embedding", "vector"}:
                continue
            summary[k] = v
    return summary


def extract_business_refs(output: dict[str, Any] | None, context_refs: dict[str, Any] | None = None) -> dict[str, Any]:
    refs = dict(context_refs or {})
    data = dict(output or {})
    for key in (
        "recommendation_id",
        "approval_id",
        "order_intent_id",
        "purchase_order_id",
        "external_order_id",
        "store_id",
        "sku",
        "supplier_id",
    ):
        if data.get(key):
            refs[key] = data[key]
        nested = data.get("business_refs")
        if isinstance(nested, dict) and nested.get(key):
            refs[key] = nested[key]
    return refs
