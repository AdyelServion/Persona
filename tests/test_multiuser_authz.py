"""Multi-user identity and authorization: server-derived user ids, ownership, 404 on foreign ids."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from persona_runtime.config import get_settings


@pytest.fixture()
def api(runtime):
    from persona_runtime.api import main

    main.set_runtime_for_tests(runtime)
    client = TestClient(main.app)
    yield client
    main.set_runtime_for_tests(None)


def _token() -> str:
    return get_settings().effective_internal_token


def _h(user_id: str | None = None) -> dict[str, str]:
    headers = {"X-Internal-Token": _token()}
    if user_id:
        headers["X-User-Id"] = user_id
    return headers


def _new_user(api, name: str, opt_in: bool = False) -> dict:
    r = api.post("/api/users", json={"display_name": name, "proactive_opt_in": opt_in}, headers=_h())
    assert r.status_code == 200, r.text
    return r.json()


def test_missing_or_wrong_internal_token_is_401(api):
    assert api.post("/api/users", json={"display_name": "Eve"}).status_code == 401
    assert (
        api.post("/api/users", json={"display_name": "Eve"}, headers={"X-Internal-Token": "nope"}).status_code
        == 401
    )
    assert api.get("/api/me", headers={"X-User-Id": "someone"}).status_code == 401
    assert api.get("/api/me", headers={"X-Internal-Token": _token()}).status_code == 401


def test_lookup_user_returns_existing_profile_or_404(api):
    alex = _new_user(api, "Alex")
    found = api.get(f"/api/users/{alex['user_id']}", headers=_h())
    assert found.status_code == 200
    body = found.json()
    assert body["user_id"] == alex["user_id"]
    assert body["display_name"] == "Alex"
    assert body["conversation_id"] == alex["conversation_id"]
    assert api.get("/api/users/does-not-exist", headers=_h()).status_code == 404
    assert api.get(f"/api/users/{alex['user_id']}").status_code == 401
    again = _new_user(api, "Alex")
    assert again["user_id"] != alex["user_id"]


def test_user_ids_are_server_generated_and_conversations_isolated(api):
    alex = _new_user(api, "Alex")
    john = _new_user(api, "John")
    assert alex["user_id"] != john["user_id"]
    assert alex["conversation_id"] != john["conversation_id"]

    convs_alex = api.get("/api/conversations", headers=_h(alex["user_id"])).json()["conversations"]
    assert [c["conversation_id"] for c in convs_alex] == [alex["conversation_id"]]


def test_body_user_id_is_ignored(api):
    alex = _new_user(api, "Alex")
    r = api.post(
        "/api/users",
        json={"display_name": "Mallory", "user_id": alex["user_id"]},
        headers=_h(),
    )
    assert r.status_code == 200
    assert r.json()["user_id"] != alex["user_id"]


@pytest.mark.parametrize(
    "method,path_tpl,body",
    [
        ("GET", "/api/conversations/{cid}/messages", None),
        ("POST", "/api/conversations/{cid}/messages", {"content": "hi"}),
        ("POST", "/api/conversations/{cid}/resume", None),
        ("POST", "/api/conversations/{cid}/opening", None),
        ("POST", "/api/conversations/{cid}/read", {}),
        ("POST", "/api/events/message_seen", "seen"),
    ],
)
def test_foreign_conversation_is_404_everywhere(api, method, path_tpl, body):
    alex = _new_user(api, "Alex")
    john = _new_user(api, "John")
    path = path_tpl.format(cid=alex["conversation_id"])
    if body == "seen":
        body = {"conversation_id": alex["conversation_id"]}
    r = api.request(method, path, json=body, headers=_h(john["user_id"]))
    assert r.status_code == 404, (path, r.status_code, r.text)


def test_unknown_conversation_is_404(api):
    alex = _new_user(api, "Alex")
    r = api.get("/api/conversations/does-not-exist/messages", headers=_h(alex["user_id"]))
    assert r.status_code == 404


def test_messages_stay_in_their_own_conversation(api, runtime):
    alex = _new_user(api, "Alex")
    john = _new_user(api, "John")
    r = api.post(
        f"/api/conversations/{alex['conversation_id']}/messages",
        json={"content": "I drive a Honda CR-Z"},
        headers=_h(alex["user_id"]),
    )
    assert r.status_code == 200
    john_msgs = api.get(
        f"/api/conversations/{john['conversation_id']}/messages", headers=_h(john["user_id"])
    ).json()["messages"]
    assert all("CR-Z" not in (m["content"] or "") for m in john_msgs)
    stored = runtime.conversation_repo.get_message(r.json()["message_id"])
    assert stored["user_id"] == alex["user_id"]


def test_memories_endpoint_only_returns_own_and_cannot_delete_foreign(api, runtime):
    alex = _new_user(api, "Alex")
    john = _new_user(api, "John")
    persona_id = runtime.settings.default_persona_id
    runtime.db["SemanticMemories"].insert_one(
        {
            "memory_id": "mem-alex-car",
            "persona_id": persona_id,
            "user_id": alex["user_id"],
            "scope": "user",
            "status": "active",
            "subject": "user",
            "predicate": "owns_car",
            "object": "Honda CR-Z",
            "fact": "User owns a Honda CR-Z",
        }
    )
    john_list = api.get("/api/memories", headers=_h(john["user_id"])).json()["memories"]
    assert all(m["memory_id"] != "mem-alex-car" for m in john_list)
    assert api.delete("/api/memories/mem-alex-car", headers=_h(john["user_id"])).status_code == 404
    alex_list = api.get("/api/memories", headers=_h(alex["user_id"])).json()["memories"]
    assert any(m["memory_id"] == "mem-alex-car" for m in alex_list)


def test_proactive_settings_are_per_user(api):
    alex = _new_user(api, "Alex", opt_in=True)
    john = _new_user(api, "John")
    assert api.get("/api/proactive-settings", headers=_h(alex["user_id"])).json()["enabled"] is True
    assert api.get("/api/proactive-settings", headers=_h(john["user_id"])).json()["enabled"] is False
    r = api.put("/api/proactive-settings", json={"quiet_start": "25:99"}, headers=_h(alex["user_id"]))
    assert r.status_code == 400


def test_public_metadata_hides_internal_brief():
    from persona_runtime.api.main import _public_metadata

    out = _public_metadata({"proactive_brief": {"hint": "x"}, "bubble_index": 0})
    assert out == {"bubble_index": 0}


# ---------------------------------------------------------------- Django session proxy


@pytest.fixture()
def django_client(monkeypatch):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")
    import django

    django.setup()
    from django.test import Client

    calls: list[dict] = []

    def fake_call(method, path, *, user_id=None, json_body=None, params=None, timeout=30.0):
        calls.append({"method": method, "path": path, "user_id": user_id, "json": json_body})
        if path == "/api/users":
            n = sum(1 for c in calls if c["path"] == "/api/users")
            return 200, {"user_id": f"u-{n}", "display_name": json_body["display_name"], "conversation_id": f"c-{n}"}
        if path == "/api/users/summaries":
            return 200, {
                "users": [{"user_id": uid, "display_name": uid, "unread_count": 0} for uid in json_body["user_ids"]]
            }
        if method == "GET" and path.startswith("/api/users/"):
            uid = path.rsplit("/", 1)[-1]
            if uid in {"missing", "no-such-user"}:
                return 404, {"detail": "User not found"}
            return 200, {"user_id": uid, "display_name": "Alex", "conversation_id": "c-alex"}
        return 200, {"ok": True, "messages": []}

    from chat import views

    monkeypatch.setattr(views, "_call", fake_call)
    client = Client()
    client.calls = calls  # type: ignore[attr-defined]
    return client


def test_django_new_chat_creates_owned_identity_and_switch_is_restricted(django_client):
    r = django_client.post("/api/users/new/", data={"display_name": "Alex"}, content_type="application/json")
    assert r.status_code == 200
    assert r.json()["user_id"] == "u-1"
    r = django_client.post("/api/users/new/", data={"display_name": "John"}, content_type="application/json")
    assert r.json()["user_id"] == "u-2"

    users = django_client.get("/api/users/").json()
    assert {u["user_id"] for u in users["users"]} == {"u-1", "u-2"}
    assert users["active_user_id"] == "u-2"

    assert (
        django_client.post("/api/users/switch/", data={"user_id": "u-1"}, content_type="application/json").status_code
        == 200
    )
    assert (
        django_client.post(
            "/api/users/switch/", data={"user_id": "someone-else"}, content_type="application/json"
        ).status_code
        == 403
    )


def test_django_resume_opens_existing_chat_on_a_fresh_session(django_client):
    from django.test import Client

    fresh = Client()
    r = fresh.post("/api/users/resume/", data={"user_id": "u-alex"}, content_type="application/json")
    assert r.status_code == 200
    assert r.json()["user_id"] == "u-alex"
    assert r.json()["conversation_id"] == "c-alex"
    listed = fresh.get("/api/users/").json()
    assert listed["active_user_id"] == "u-alex"
    assert {u["user_id"] for u in listed["users"]} == {"u-alex"}

    fresh.post(
        "/api/send/",
        data={"conversation_id": "c-alex", "content": "hi again"},
        content_type="application/json",
    )
    sends = [c for c in django_client.calls if c["path"].endswith("/messages") and c["method"] == "POST"]
    assert sends[-1]["user_id"] == "u-alex"

    missing = fresh.post("/api/users/resume/", data={"user_id": "missing"}, content_type="application/json")
    assert missing.status_code == 404
    assert missing.json()["error"] == "No chat found for that user id"
    assert {u["user_id"] for u in fresh.get("/api/users/").json()["users"]} == {"u-alex"}

    bad = fresh.post("/api/users/resume/", data={"user_id": "not a user"}, content_type="application/json")
    assert bad.status_code == 400
    assert (
        fresh.post("/api/users/switch/", data={"user_id": "someone-else"}, content_type="application/json").status_code
        == 403
    )


def test_django_resume_respects_browser_user_cap(django_client):
    from django.test import override_settings

    with override_settings(MAX_USERS_PER_BROWSER=1):
        created = django_client.post(
            "/api/users/new/", data={"display_name": "Alex"}, content_type="application/json"
        )
        assert created.status_code == 200
        resumed = django_client.post(
            "/api/users/resume/", data={"user_id": "u-other"}, content_type="application/json"
        )
        assert resumed.status_code == 429
        assert {u["user_id"] for u in django_client.get("/api/users/").json()["users"]} == {"u-1"}


def test_bootstrap_forgets_a_remembered_user_that_no_longer_exists(django_client, monkeypatch):
    created = django_client.post(
        "/api/users/new/", data={"display_name": "Alex"}, content_type="application/json"
    )
    assert created.status_code == 200

    def gone(method, path, *, user_id=None, json_body=None, params=None, timeout=30.0):
        if method == "GET" and path.startswith("/api/users/"):
            return 404, {"detail": "User not found"}
        return 200, {"ok": True, "messages": []}

    from chat import views

    monkeypatch.setattr(views, "_call", gone)
    boot = django_client.get("/api/bootstrap/")
    assert boot.status_code == 200
    assert boot.json()["needs_user"] is True
    assert django_client.get("/api/users/").json()["users"] == []


def test_django_proxy_forwards_session_user_not_body_user(django_client):
    django_client.post("/api/users/new/", data={"display_name": "Alex"}, content_type="application/json")
    django_client.post(
        "/api/send/",
        data={"conversation_id": "c-1", "content": "hi", "user_id": "attacker"},
        content_type="application/json",
    )
    sends = [c for c in django_client.calls if c["path"].endswith("/messages") and c["method"] == "POST"]
    assert sends and sends[-1]["user_id"] == "u-1"
    assert "user_id" not in (sends[-1]["json"] or {})


def test_django_proxy_without_identity_needs_user(django_client):
    r = django_client.post(
        "/api/send/", data={"conversation_id": "c-1", "content": "hi"}, content_type="application/json"
    )
    assert r.status_code == 409
    assert r.json()["needs_user"] is True
