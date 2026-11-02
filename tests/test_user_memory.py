"""Per-user memory: isolation (Alex / John / David), corrections, temporal state, delete, restart."""

from __future__ import annotations

import pytest

from persona_runtime.config import get_settings
from persona_runtime.db import MEMORY_COLLECTIONS
from persona_runtime.graph.runtime import PersonaRuntime
from persona_runtime.memory.schemas import MemoryCandidate


def _user(runtime, name: str) -> tuple[str, str]:
    user = runtime.user_repo.create(display_name=name)
    conv = runtime.conversation_repo.get_or_create(runtime.settings.default_persona_id, user["user_id"])
    return user["user_id"], conv["conversation_id"]


def _say(runtime, user_id: str, conversation_id: str, text: str) -> dict:
    msg = runtime.conversation_repo.add_message(conversation_id=conversation_id, sender="user", content=text)
    return runtime.run(
        event_type="user_message",
        user_id=user_id,
        conversation_id=conversation_id,
        incoming_message=text,
        user_message_id=msg["message_id"],
        pending_messages=[msg],
    )


def _active_semantic(runtime, user_id: str, predicate: str) -> list[dict]:
    col = runtime.db[MEMORY_COLLECTIONS["semantic"]]
    return list(
        col.find(
            {
                "persona_id": runtime.settings.default_persona_id,
                "user_id": user_id,
                "predicate": predicate,
                "status": "active",
            }
        )
    )


def _consolidate(runtime, user_id: str, conversation_id: str, *cands: MemoryCandidate) -> list[dict]:
    return runtime.services.consolidator.consolidate(
        persona_id=runtime.settings.default_persona_id,
        user_id=user_id,
        conversation_id=conversation_id,
        candidates=list(cands),
    )


def _sem(predicate: str, obj: str, fact: str, **kw) -> MemoryCandidate:
    return MemoryCandidate(
        memory_type="semantic",
        importance=0.85,
        confidence=0.9,
        fact=fact,
        subject="user",
        predicate=predicate,
        object=obj,
        **kw,
    )


@pytest.fixture()
def three_users(runtime):
    alex = _user(runtime, "Alex")
    john = _user(runtime, "John")
    david = _user(runtime, "David")
    _say(runtime, *alex, "My name is Alex and I drive a Honda CR-Z")
    _say(runtime, *john, "My name is John. I love photography")
    _say(runtime, *david, "I drive a Honda Civic and I support Arsenal")
    return {"alex": alex, "john": john, "david": david}


def test_each_user_only_has_their_own_facts(runtime, three_users):
    alex, john, david = (three_users[k][0] for k in ("alex", "john", "david"))
    assert [m["object"] for m in _active_semantic(runtime, alex, "owns_car")] == ["Honda CR-Z"]
    assert [m["object"] for m in _active_semantic(runtime, david, "owns_car")] == ["Honda Civic"]
    assert _active_semantic(runtime, john, "owns_car") == []
    assert [m["object"] for m in _active_semantic(runtime, john, "hobby")] == ["photography"]
    assert _active_semantic(runtime, alex, "hobby") == []
    assert [m["object"] for m in _active_semantic(runtime, david, "supports_team")] == ["Arsenal"]


def test_retrieval_never_returns_another_users_memory(runtime, three_users):
    retriever = runtime.services.memory_retriever
    persona_id = runtime.settings.default_persona_id
    for key, (uid, cid) in three_users.items():
        mems = retriever.retrieve(persona_id=persona_id, user_id=uid, query="what car do I drive honda", conversation_id=cid)
        assert all(m.get("user_id") in (uid, None) for m in mems), key
        texts = " ".join(str(m.get("object") or m.get("fact") or "") for m in mems)
        if key == "john":
            assert "CR-Z" not in texts and "Civic" not in texts
        if key == "alex":
            assert "Civic" not in texts


def test_profile_card_and_user_memory_service_are_isolated(runtime, three_users):
    persona_id = runtime.settings.default_persona_id
    alex = three_users["alex"][0]
    john = three_users["john"][0]
    card = runtime.user_memory.profile_card(persona_id, john)
    assert all(c["user_id"] == john for c in card)
    assert not any("CR-Z" in str(c.get("object")) for c in card)
    listed = runtime.user_memory.list_for_user(persona_id, alex)
    assert listed and all(m["memory_id"] for m in listed)
    assert not any("photography" == m["value"] for m in listed)


def test_persona_scoped_doc_with_foreign_user_id_is_not_returned(runtime, three_users):
    persona_id = runtime.settings.default_persona_id
    alex = three_users["alex"][0]
    john = three_users["john"][0]
    runtime.db[MEMORY_COLLECTIONS["semantic"]].insert_one(
        {
            "memory_id": "leaky",
            "persona_id": persona_id,
            "user_id": alex,
            "scope": "persona",
            "status": "active",
            "subject": "user",
            "predicate": "owns_car",
            "object": "Honda CR-Z",
            "fact": "User owns a Honda CR-Z",
            "importance": 0.9,
            "confidence": 0.9,
        }
    )
    got = runtime.memory_repo.get_active("semantic", persona_id=persona_id, user_id=john)
    assert all(m["memory_id"] != "leaky" for m in got)


def test_name_correction_supersedes_old_value(runtime):
    uid, cid = _user(runtime, "Alex")
    _say(runtime, uid, cid, "My name is Alex")
    _say(runtime, uid, cid, "Actually, my name is Jordan")
    names = [m["object"] for m in _active_semantic(runtime, uid, "name")]
    assert names == ["Jordan"]
    old = runtime.db[MEMORY_COLLECTIONS["semantic"]].find_one({"user_id": uid, "predicate": "name", "object": "Alex"})
    assert old and old["status"] == "superseded" and old.get("superseded_by")


def test_multi_valued_hobbies_accumulate_and_dedupe(runtime):
    uid, cid = _user(runtime, "Sam")
    _consolidate(runtime, uid, cid, _sem("hobby", "photography", "User enjoys photography"))
    _consolidate(runtime, uid, cid, _sem("hobby", "hiking", "User enjoys hiking"))
    _consolidate(runtime, uid, cid, _sem("hobby", "Photography", "User enjoys photography"))
    hobbies = sorted(m["object"].lower() for m in _active_semantic(runtime, uid, "hobby"))
    assert hobbies == ["hiking", "photography"]


def test_temporary_state_is_not_a_stable_preference(runtime):
    uid, cid = _user(runtime, "Tess")
    _say(runtime, uid, cid, "I'm having a coffee right now")
    assert _active_semantic(runtime, uid, "morning_drink") == []
    assert _active_semantic(runtime, uid, "favourite_drink") == []
    working = list(runtime.db[MEMORY_COLLECTIONS["working"]].find({"user_id": uid, "status": "active"}))
    assert working and all(w.get("temporal") == "temporary" and w.get("valid_until") for w in working)
    card = runtime.user_memory.profile_card(runtime.settings.default_persona_id, uid)
    assert not any("coffee" in str(c.get("fact") or "").lower() for c in card)


def test_former_interest_is_labelled_and_kept_off_the_profile_card(runtime):
    uid, cid = _user(runtime, "Gil")
    _say(runtime, uid, cid, "I used to play guitar but not anymore")
    hobbies = _active_semantic(runtime, uid, "hobby")
    assert hobbies and hobbies[0]["interest_status"] == "former"
    card = runtime.user_memory.profile_card(runtime.settings.default_persona_id, uid)
    assert not any(c.get("object") == "guitar" for c in card)


def test_deleted_memory_does_not_resurface(runtime):
    uid, cid = _user(runtime, "Dee")
    _say(runtime, uid, cid, "I drive a Toyota Corolla")
    persona_id = runtime.settings.default_persona_id
    car = _active_semantic(runtime, uid, "owns_car")
    assert car
    assert runtime.user_memory.delete(persona_id, uid, car[0]["memory_id"])
    assert _active_semantic(runtime, uid, "owns_car") == []
    mems = runtime.services.memory_retriever.retrieve(
        persona_id=persona_id, user_id=uid, query="what car do I drive toyota", conversation_id=cid
    )
    assert all(m.get("memory_id") != car[0]["memory_id"] for m in mems)
    ctx = runtime.conversation_context_repo.get(cid) or {}
    assert not any("corolla" in str(f.get("object") or "").lower() for f in ctx.get("user_facts_this_conversation") or [])


def test_delete_cannot_touch_someone_elses_memory(runtime, three_users):
    persona_id = runtime.settings.default_persona_id
    alex = three_users["alex"][0]
    john = three_users["john"][0]
    car = _active_semantic(runtime, alex, "owns_car")[0]
    assert runtime.user_memory.delete(persona_id, john, car["memory_id"]) is False
    assert _active_semantic(runtime, alex, "owns_car")


def test_memories_survive_a_runtime_restart(runtime, fake_llm, three_users):
    restarted = PersonaRuntime(settings=get_settings(), llm=fake_llm, db=runtime.db)
    alex = three_users["alex"][0]
    assert [m["object"] for m in _active_semantic(restarted, alex, "owns_car")] == ["Honda CR-Z"]


def test_similar_facts_for_different_users_stay_separate(runtime):
    a, ca = _user(runtime, "A")
    b, cb = _user(runtime, "B")
    _consolidate(runtime, a, ca, _sem("hobby", "photography", "User enjoys photography"))
    _consolidate(runtime, b, cb, _sem("hobby", "photography", "User enjoys photography"))
    da = _active_semantic(runtime, a, "hobby")
    db_ = _active_semantic(runtime, b, "hobby")
    assert len(da) == 1 and len(db_) == 1
    assert da[0]["memory_id"] != db_[0]["memory_id"]


def test_migration_is_dry_run_by_default_and_rescopes_on_apply(runtime):
    from persona_runtime.users.migration import migrate

    persona_id = runtime.settings.default_persona_id
    conv = runtime.conversation_repo.get_or_create(persona_id, "local-user")
    runtime.db[MEMORY_COLLECTIONS["semantic"]].insert_one(
        {
            "memory_id": "legacy-1",
            "persona_id": persona_id,
            "user_id": "local-user",
            "scope": "persona",
            "status": "active",
            "subject": "user",
            "predicate": "owns_car",
            "object": "Honda CR-Z",
        }
    )
    report = migrate(runtime.db)
    assert report["applied"] is False and report["memories_rescoped"] >= 1
    assert runtime.db[MEMORY_COLLECTIONS["semantic"]].find_one({"memory_id": "legacy-1"})["scope"] == "persona"
    assert runtime.user_repo.get("local-user") is None

    migrate(runtime.db, apply=True)
    assert runtime.db[MEMORY_COLLECTIONS["semantic"]].find_one({"memory_id": "legacy-1"})["scope"] == "user"
    assert runtime.user_repo.get("local-user")["display_name"] == "You"
    assert runtime.proactive_settings_repo.get("local-user", persona_id)["enabled"] is False
    assert conv["user_id"] == "local-user"
    again = migrate(runtime.db, apply=True)
    assert again["memories_rescoped"] == 0 and again["app_users_created"] == 0
