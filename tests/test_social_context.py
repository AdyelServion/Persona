"""Social context provider: only explicitly authorized, per-user sources."""

from __future__ import annotations

from persona_runtime.user_context.provider import (
    AppUserProfileSource,
    MinimalUserContextProvider,
    SocialContextProvider,
)


class BrokenSource:
    name = "broken"

    def load(self, user_id):
        raise RuntimeError("source down")


def test_app_user_profile_is_the_default_authorized_source(runtime):
    alex = runtime.user_repo.create(display_name="Alex", interests=["cars", "photography"])
    john = runtime.user_repo.create(display_name="John")
    provider = SocialContextProvider.default(runtime.db)
    ctx = provider.load_user_context(alex["user_id"])
    assert ctx["display_name"] == "Alex"
    assert {c["value"] for c in ctx["authorized_context"]} == {"cars", "photography"}
    assert all(c["source"] == "app_user_profile" for c in ctx["authorized_context"])
    assert provider.load_authorized_context(john["user_id"]) == []


def test_unknown_user_and_broken_sources_degrade_safely(runtime):
    provider = SocialContextProvider([BrokenSource(), AppUserProfileSource(runtime.db)])
    ctx = provider.load_user_context("nobody")
    assert ctx["authorized_context"] == [] and ctx["display_name"] is None


def test_minimal_provider_still_available():
    assert MinimalUserContextProvider().load_user_context("x")["authorized_context"] == []


def test_runtime_hydrates_social_context_for_the_turn_user_only(runtime):
    persona_id = runtime.settings.default_persona_id
    alex = runtime.user_repo.create(display_name="Alex", interests=["cars"])
    john = runtime.user_repo.create(display_name="John", interests=["chess"])
    conv = runtime.conversation_repo.get_or_create(persona_id, john["user_id"])
    msg = runtime.conversation_repo.add_message(conversation_id=conv["conversation_id"], sender="user", content="hey")
    result = runtime.run(
        event_type="user_message",
        user_id=john["user_id"],
        conversation_id=conv["conversation_id"],
        incoming_message="hey",
        user_message_id=msg["message_id"],
        pending_messages=[msg],
    )
    values = {c["value"] for c in result.get("social_context") or []}
    assert values == {"chess"}
    assert alex["user_id"] != john["user_id"]
