# Multi-user, extroverted Sarah and proactive outbound

Sarah is an AI persona. Each person who chats with her gets their own identity, conversation and
memory. Sarah can also start conversations, but only for users who opted in, within strict caps.
Mentorship is out of scope.

## Identity and trust boundary

```
Browser ──(signed session cookie, CSRF)──▶ Django (chat/) ──(X-Internal-Token + X-User-Id)──▶ FastAPI ──▶ LangGraph ──▶ MongoDB
```

- **New chat** asks for a name, then creates an `AppUsers` record through
  `POST /api/users` on FastAPI. The new `user_id` is shown in the header with a Copy
  button. There are no passwords: the user id is the credential that reopens that chat.
- **Paste a user id** in the same dialog (`POST /api/users/resume/`). Django looks the id
  up (`GET /api/users/{id}`, 404 if it does not exist) and only then adds it to this
  browser's signed-cookie session. An unknown id does not create a user. One browser can
  hold several opened chats (capped by `MAX_USERS_PER_BROWSER`), and the sidebar switches
  between them. The cookie only remembers chats already opened here. If a remembered
  id no longer exists, it is dropped and the dialog opens again.
- Django never forwards a `user_id` from a chat message body. The proxy always sends the
  session's active user as `X-User-Id`. Switching to an id that was not created or resumed
  on this browser returns 403.
- FastAPI rejects any call without the shared `X-Internal-Token` (401). It ignores
  `user_id` in request bodies and checks conversation ownership on every route through
  `owned_conversation_or_404`. A foreign conversation returns **404, not 403**, so its
  existence isn't revealed.
- Set `INTERNAL_API_TOKEN` in production (`render.yaml` generates one). If it's unset, a
  development token is used.

### IDs

| ID | Where |
|---|---|
| `user_id` | `AppUsers`; on every conversation, message, memory, topic, setting, job and event |
| `persona_id` | `sarah_taylor_001` (the runtime accepts others) |
| `conversation_id` | one primary conversation per (persona, user) |
| `message_id` | `ConversationMessages`; proactive bubbles also carry `outbound_id` |
| `memory_id` | typed memory collections |

## Memory isolation and taxonomy

Facts derived from conversation are stored with `scope="user"` and the owner's `user_id`.
Only Sarah's own canon is persona-scoped. Retrieval filters by `(persona_id, user_id)`
before ranking, and the profile card and the `KNOWN_ABOUT_THIS_USER` prompt section are
built from the current user's memories only.

Each fact carries a `category` (identity, occupation, hobby, interest, sports, music, food,
travel, lifestyle, event, …), a `memory_key`, a `temporal` value
(stable / temporary / former), `status` (active / superseded / deleted) and
`superseded_by`.

- **Correction** ("actually my name is Jordan") supersedes the old value. Multi-valued keys
  (hobbies, interests) are de-duplicated rather than replaced.
- **Former** interests ("I used to play guitar") stay as history and are never presented as
  current.
- **Delete:** `DELETE /api/memories/{id}` marks the memory deleted. It never resurfaces,
  and it can only delete the caller's own memories. The deletion is recorded as a
  `memory_deleted` event.
- `scripts/migrate_multiuser.py` is a dry run by default (`--apply` to write) and safe to
  re-run. It re-scopes legacy user facts to `scope="user"`, backfills `AppUsers` and
  disabled `ProactiveSettings`, and sets `user_id` on any messages that have no owner.

## Extrovert engagement layer

The layer lives in `persona_runtime/conversation/extrovert.py` and `discovery.py`, on top of
the existing engagement strategy.

- **Protected turns.** It never overrides direct answers, empathy, natural closes or
  respectful disagreement.
- **When it steps in.** On idle turns, it takes initiative in Sarah-led mode, or after a
  thin reply ("ok", "yeah") when Sarah didn't just ask a question.
- **Topic choice.** It revisits a known interest, citing evidence from the user's own
  memory, or opens a fresh area.
- **Progressive discovery.** It suggests at most one discovery target per turn. Areas unlock
  by stage (getting to know → building → familiar) and are spaced by
  `discovery_min_turn_gap`. Declined topics are never pushed again.
- **Self-disclosure.** Sarah shares something about herself, grounded in her Preferences
  canon, so the exchange stays reciprocal instead of interview-style.
- **Validator.** It flags more than `max_questions_per_reply` questions, and any banned
  phrase from the personality profile.
- **Sarah-led mode.** After a user replies to an outbound or opening message, Sarah keeps
  leading for `SARAH_LED_TURNS` turns (default 4).

**Tension with canon.** `Personality.md` describes Sarah as warm but "not naturally dominant".
The layer therefore takes initiative through curiosity and shared interests, not by
monopolising the conversation. It asks one question at most, reacts first, and backs off
from declined topics.

## Proactive outbound engine

These rules are in `persona_runtime/outbound/`.

**Permission and limits:**

- Off by default, both globally (`PROACTIVE_OUTBOUND_ENABLED`) and per user (opt-in
  checkbox on New chat, or the ⚙ settings).
- Engagement policy **v2** (see `ProactiveSettings.engagement_policy_version`) uses
  per-user **evaluation scheduling**: randomized intervals from
  `[5,10,15,20,25,30,35,40,45,50,60]` minutes (`next_evaluation_at`, persisted in Mongo).
  Defaults: **2/hour, 8/day, 28/week**, `PROACTIVE_MIN_GAP_MINUTES=5` (legacy v1 docs still
  use hour-based gap until upgraded on read).
- Quiet hours apply in the user's own timezone (default 22:00–08:00). Evaluations during quiet
  hours are **queued** until quiet end (not sent immediately).
- Users can pause or mute message types.
- Saying something like "stop messaging me first" in chat opts the user out immediately
  and cancels pending jobs.

**When Sarah messages first.** The worker loads users with `next_evaluation_at <= now`
(not a fixed global scan interval). Gates: globally disabled, not opted in, paused, type
muted, **awaiting reply**, already scheduled, min gap / backoff, hourly / daily / weekly caps,
consecutive-initiation cap (v2). Quiet hours defer evaluation.

Each evaluation analyzes the last 5–10 messages, memories, and topic state, collects rule
based trigger **candidates**, then an LLM structured decision (`proactive_engagement_decision`)
chooses send/skip/strategy (rule engine fallback in tests). Reasons are chosen in priority order:

1. `event_followup`: asks how a past event went, without assuming the outcome.
2. `conversation_resumption`
3. `weekend_followup`: only if a weekend habit is known.
4. `hobby_followup`
5. `interest_followup`: for sports, it never claims results.
6. `new_topic`

`returning_user_greeting` is used when an opted-in user comes back after 3 hours or more.

**Multi-turn.** One outbound is a burst of 1–3 bubbles (`PROACTIVE_MAX_BUBBLES`) sharing one
`outbound_id`, with at most one question. It counts once toward the caps. **Nothing else is
sent until the user replies.** The reply switches the conversation into Sarah-led mode, so
she carries the topic forward over several turns.

**Safety.**

- Jobs are idempotent (`{user}:{type}:{subject}:{eval_bucket}`) and expire after
  `PROACTIVE_JOB_TTL_HOURS`.
- At execution time the engine re-checks ownership, expiry, every gate, and whether the
  user has spoken first. A user message cancels any scheduled outbound job.
- An outbound left unanswered for 72h raises the backoff level. After 4 consecutive misses,
  outbound pauses automatically.
- Proactive messages are never artificially delayed.

**Delivery.** `PROACTIVE_DELIVERY=in_app` marks messages delivered so the polling UI shows
them with a "messaged first" tag. `test` uses `TestDelivery`, which records messages and
sends nothing. Tests never send real notifications.

## Social context

`persona_runtime/user_context/provider.py` defines `SocialContextProvider`, which merges
pluggable `ContextSource`s. Today it has one source, `AppUserProfileSource`, which provides
the display name, timezone and self-declared interests. Each item is labelled
`authorized_context`. A failing source is skipped. External sources (calendar, social
profiles) can be added later as new `ContextSource`s that only return data the user
authorized.

## API

FastAPI (internal, token-protected):

| Method | Path | Notes |
|---|---|---|
| POST | `/api/users` | create user (+ settings) |
| GET | `/api/users/{id}` | look up an existing user; 404, never creates |
| POST | `/api/users/summaries` | sidebar summaries for this browser's opened chats |
| GET | `/api/me` | current user |
| GET/POST | `/api/conversations` | list / get-or-create own conversation |
| GET/POST | `/api/conversations/{id}/messages` | owned only |
| POST | `/api/conversations/{id}/resume` · `/opening` · `/read` | owned only |
| POST | `/api/events/message_seen` | |
| GET/PUT | `/api/proactive-settings` | enabled, quiet hours, pause, muted types |
| GET | `/api/memories` | own memories |
| DELETE | `/api/memories/{id}` | own memory only |

Django (browser-facing, CSRF): `/api/users/`, `/api/users/new/`, `/api/users/resume/`, `/api/users/switch/`,
`/api/bootstrap/`, `/api/messages/`, `/api/send/`, `/api/seen/`, `/api/proactive-settings/`.

## Analytics

The `Events` collection records `proactive_evaluated`, `proactive_skipped`,
`proactive_interval_selected`, `proactive_quiet_queued`, `user_created`, `proactive_scheduled`, `proactive_sent`,
`proactive_replied`, `proactive_ignored`, `proactive_suppressed`, `proactive_cancelled`,
`proactive_blocked`, `proactive_opt_out`, `proactive_settings_changed` and `memory_deleted`.

```powershell
python scripts\engagement_report.py --days 7
```

The report shows counts, the reply rate overall and per type, average bubbles per outbound,
reasons for suppression and cancellation, and how many users are opted in, awaiting a
reply, or auto-paused.

## Tests

| File | Covers |
|---|---|
| `tests/test_multiuser_authz.py` | token, ownership 404s, ignored body `user_id`, Django session switching |
| `tests/test_user_memory.py` | Alex/John/David isolation, correction, former, delete, migration |
| `tests/test_extrovert_engine.py` | protected strategies, discovery, self-disclosure, validator |
| `tests/test_proactive_engine.py` | gates, caps, timezones, triggers, bursts, idempotency, opt-out, expiry, worker, analytics |
| `tests/test_social_context.py` | provider merging and isolation |
| `tests/test_qa_multiuser_suites.py` | QA suites MULTIUSER / EXTROVERT / OUTBOUND end to end |

## Known limitations

- There are no passwords. Anyone who has a user id can open that chat. The cookie only
  remembers chats already opened on this browser; clearing it does not delete the chat.
- Real-time delivery is polling. There are no web push or email channels yet; the delivery
  adapter is the extension point.
- Fact extraction and topic classification use keywords and the LLM, so unusual phrasing
  can be missed.
- Opt-out detection uses phrase matching. The ⚙ settings toggle is the reliable control.
- The proactive scan runs inside the web process's worker thread. With several web
  instances, idempotency keys prevent duplicates, but every instance still runs the scan.
