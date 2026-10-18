"""Publish versioned run events. Kafka is not an execution path."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import KafkaInbox
from backend.app.settings import kafka_bootstrap

TOPIC = "evalforge.runs"


def publish_event(payload: dict) -> bool:
    servers = kafka_bootstrap()
    if not servers:
        return True
    try:
        from kafka import KafkaProducer

        producer = KafkaProducer(
            bootstrap_servers=servers,
            acks="all",
            retries=1,
            request_timeout_ms=2000,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        )
        producer.send(TOPIC, payload)
        producer.flush(timeout=2)
        producer.close()
    except Exception:
        return False
    return True


def record_inbox(session: Session, event_id: str) -> bool:
    existing = session.scalar(select(KafkaInbox).where(KafkaInbox.event_id == event_id))
    if existing is not None:
        return False
    session.add(KafkaInbox(event_id=event_id, processed_at=datetime.now(timezone.utc)))
    session.flush()
    return True


def consume_once() -> int:
    servers = kafka_bootstrap()
    if not servers:
        return 0
    try:
        from kafka import KafkaConsumer
    except Exception:
        return 0
    try:
        consumer = KafkaConsumer(
            TOPIC,
            bootstrap_servers=servers,
            group_id="evalforge-inbox",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            consumer_timeout_ms=1000,
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        )
    except Exception:
        return 0
    recorded = 0
    from backend.app.db import session_scope

    try:
        for message in consumer:
            payload = message.value if isinstance(message.value, dict) else {}
            event_id = str(payload.get("event_id") or "")
            if not event_id:
                continue
            with session_scope() as session:
                if record_inbox(session, event_id):
                    recorded += 1
    except Exception:
        return recorded
    finally:
        consumer.close()
    return recorded
