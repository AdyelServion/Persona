# Persona clock and timeline

Sarah’s day is driven by an authoritative clock and a persisted event timeline.
The language model never invents the current date, weekday, or time, and does not
silently rewrite completed history.

## Clock

[`persona_runtime/life/clock.py`](../persona_runtime/life/clock.py) builds a
`ClockSnapshot` from the injectable UTC clock (`persona_runtime.db.time_utils.utcnow`
/ `set_clock`) and the persona IANA timezone (`PERSONA_TIMEZONE`, default
`Europe/London`).

Each conversation hydrate injects the snapshot into graph state and into the
generation context as a `CLOCK` block marked authoritative.

### Freezing time in tests

```python
from datetime import datetime, timezone
from persona_runtime.db.time_utils import set_clock

fixed = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)
set_clock(lambda: fixed)
# ... exercise TimelineEngine / LifeSimulator ...
set_clock(None)
```

## Timeline events

Collection: `TimelineEvents`.

| Field | Notes |
| --- | --- |
| `event_id` | Stable id derived from persona + local date + activity + start |
| `status` | `planned` \| `active` \| `completed` \| `cancelled` \| `skipped` |
| `source` | `routine_template` \| `simulation` \| `confirmed` \| `correction` |
| `scheduled_start` / `scheduled_end` | From the daily routine template |
| `actual_start` / `actual_end` | Set only by `TimelineEngine.advance` |

Daily plans still come from `build_daily_plan` in
[`persona_runtime/life/simulator.py`](../persona_runtime/life/simulator.py).
They are materialised **once** per local date as `planned` rows and are not
rewritten on later requests. Yesterday’s rows remain in the collection.

## Advancement policy

Status changes happen **only** inside `TimelineEngine.advance(now)`:

1. Ensure today’s planned events exist.
2. Walk due `planned` events in scheduled order.
3. At most one event is `active`.
4. Completing the previous active event and activating the next is one step.
5. Location transitions must be allowed (office → home always via `commuting`).
6. A second advance at the same clock with no due work is a no-op.
7. Compare-and-swap on `PersonaState.state_version` prevents duplicate workers
   from applying the same transitions twice.

Reading the timeline never promotes `planned` → `completed` merely because the
wall clock passed.

## World state

`PersonaState.current_state` is derived from the active timeline event and
includes `active_event_id`, `last_completed_event_id`, `next_planned_event_id`,
`transport_mode`, and `current_meal`. Meal details still live in
`experience_events`, linked via `timeline_event_id` when materialised.

## Fact sources

| Concern | Source of truth |
| --- | --- |
| Identity / biography | Canonical facts (`SEED_CANONICAL_FACTS`) |
| Transport | `owns_personal_vehicle`, `commute_mode` (separate predicates) |
| Employment / projects | `EMPLOYMENT_PROFILE`, `CURRENT_PROJECTS` |
| Current place / activity | Active timeline event → world state |
| Past day | Completed `TimelineEvents` for that local date |
| Future routine | Planned timeline events — answered as **simulated** with uncertainty |
| Confirmed appointments | `source=confirmed` — may answer as established |

Personal car ownership and company vehicle access are never the same fact.
Sarah does not own a personal car; she uses public transport by default.

## Request path

1. Clock snapshot
2. Canonical facts
3. Ensure day events + `advance`
4. World state, memories, recent messages
5. Question grounding → answer plan
6. Generate → validate against clock / facts / event ids
7. Persist experiences and messages

## Observability

Structured logs (no message bodies):

- `turn_clock` — UTC/local time, `state_version`, active event, transition count
- `timeline_advance` / `timeline_cas_conflict` / `timeline_transition_blocked`
- `turn_validation_ok` / `response_validation_failed`
- `llm_complete` — latency and token usage
