"""Delivery adapters for proactive messages.

InAppDelivery: messages are already persisted; the web UI shows them on its next poll.
TestDelivery: records deliveries in memory — tests must never send real notifications.
"""

from __future__ import annotations

from typing import Any, Protocol

from persona_runtime.db.time_utils import utcnow


class DeliveryAdapter(Protocol):
    channel: str

    def deliver(
        self, *, user_id: str, conversation_id: str, message_ids: list[str], proactive_type: str
    ) -> dict[str, Any]:
        ...


class InAppDelivery:
    channel = "in_app"

    def __init__(self, conversation_repo):
        self.conversation_repo = conversation_repo

    def deliver(self, *, user_id, conversation_id, message_ids, proactive_type) -> dict[str, Any]:
        self.conversation_repo.update_messages(
            list(message_ids), {"delivery_status": "delivered", "delivered_at": utcnow()}
        )
        return {"channel": self.channel, "delivered": len(message_ids)}


class TestDelivery:
    __test__ = False  # not a pytest test class
    channel = "test"

    def __init__(self, conversation_repo=None):
        self.conversation_repo = conversation_repo
        self.sent: list[dict[str, Any]] = []

    def deliver(self, *, user_id, conversation_id, message_ids, proactive_type) -> dict[str, Any]:
        self.sent.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_ids": list(message_ids),
                "proactive_type": proactive_type,
            }
        )
        if self.conversation_repo is not None:
            self.conversation_repo.update_messages(list(message_ids), {"delivery_status": "delivered"})
        return {"channel": self.channel, "delivered": len(message_ids)}


def get_delivery(settings, conversation_repo) -> DeliveryAdapter:
    if getattr(settings, "proactive_delivery", "in_app") == "test":
        return TestDelivery(conversation_repo)
    return InAppDelivery(conversation_repo)
