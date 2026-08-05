"""Checkpoint 1 — persistent follow-up sessions (user + recommendation)."""

from __future__ import annotations

import asyncio

from agent.sessions import (
    clear_follow_up_session,
    follow_up_session_id,
    get_follow_up_session,
)
from services import recommendation_service


def test_follow_up_session_id_stable_per_user_and_recommendation():
    assert follow_up_session_id("alex.store", "REC-1") == "replenishment:alex.store:REC-1"
    assert follow_up_session_id("alex.store", "REC-1") == follow_up_session_id(
        "alex.store", "REC-1"
    )
    assert follow_up_session_id("alex.store", "REC-1") != follow_up_session_id(
        "blake.buyer", "REC-1"
    )
    assert follow_up_session_id("alex.store", "REC-1") != follow_up_session_id(
        "alex.store", "REC-2"
    )
    assert follow_up_session_id("", "REC-1") == "replenishment:anonymous:REC-1"


def test_same_user_recommendation_preserves_conversation_items():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="session preserve"
    )
    session = get_follow_up_session("alex.store", rec.recommendation_id)
    asyncio.run(
        session.add_items(
            [
                {"role": "user", "content": "Why this quantity?"},
                {"role": "assistant", "content": "Because forecast and case pack."},
            ]
        )
    )
    again = get_follow_up_session("alex.store", rec.recommendation_id)
    items = asyncio.run(again.get_items())
    assert len(items) == 2
    assert items[0]["content"] == "Why this quantity?"
    assert items[1]["role"] == "assistant"


def test_different_recommendations_have_isolated_sessions():
    rec_a = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="iso-a"
    )
    rec_b = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1002", rationale="iso-b"
    )
    sess_a = get_follow_up_session("alex.store", rec_a.recommendation_id)
    sess_b = get_follow_up_session("alex.store", rec_b.recommendation_id)
    asyncio.run(sess_a.add_items([{"role": "user", "content": "about A"}]))
    asyncio.run(sess_b.add_items([{"role": "user", "content": "about B"}]))

    assert [i["content"] for i in asyncio.run(sess_a.get_items())] == ["about A"]
    assert [i["content"] for i in asyncio.run(sess_b.get_items())] == ["about B"]


def test_different_users_have_isolated_sessions_on_same_recommendation():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="iso-user"
    )
    alex = get_follow_up_session("alex.store", rec.recommendation_id)
    blake = get_follow_up_session("blake.buyer", rec.recommendation_id)
    asyncio.run(alex.add_items([{"role": "user", "content": "alex note"}]))
    asyncio.run(blake.add_items([{"role": "user", "content": "blake note"}]))

    assert [i["content"] for i in asyncio.run(alex.get_items())] == ["alex note"]
    assert [i["content"] for i in asyncio.run(blake.get_items())] == ["blake note"]


def test_clear_follow_up_session_removes_only_conversation_memory():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="clear memory only"
    )
    session = get_follow_up_session("alex.store", rec.recommendation_id)
    asyncio.run(
        session.add_items(
            [
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
            ]
        )
    )
    assert len(asyncio.run(session.get_items())) == 2

    deleted = clear_follow_up_session("alex.store", rec.recommendation_id)
    assert deleted == 2
    assert asyncio.run(session.get_items()) == []

    # Business record remains authoritative and unchanged.
    stored = recommendation_service.get_recommendation(rec.recommendation_id)
    assert stored["recommendation_id"] == rec.recommendation_id
    assert stored["agent_recommended_quantity"] == rec.agent_recommended_quantity
    assert stored["rationale"] == "clear memory only"


def test_session_sanitizes_sensitive_keys():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="sanitize"
    )
    session = get_follow_up_session("alex.store", rec.recommendation_id)
    asyncio.run(
        session.add_items(
            [
                {
                    "role": "user",
                    "content": "hi",
                    "api_key": "sk-secret",
                    "nested": {"password": "p@ss"},
                }
            ]
        )
    )
    items = asyncio.run(session.get_items())
    assert items[0]["api_key"] == "[redacted]"
    assert items[0]["nested"]["password"] == "[redacted]"
    assert items[0]["content"] == "hi"
