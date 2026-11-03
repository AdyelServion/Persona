# Proactive engagement QA report

Generated: 2026-11-03 (implementation pass)

## Summary

| Area | Tests | Result |
|------|-------|--------|
| Scheduling / intervals | `test_proactive_engagement_v2`, `test_proactive_engine` | Pass |
| Policy caps (v1 + v2) | `test_proactive_engine`, `test_proactive_engagement_v2` | Pass |
| Context analysis | `test_proactive_engagement_v2` | Pass |
| End-to-end outbound | `test_proactive_engine` (21 cases) | Pass |
| Multi-user isolation | `test_proactive_engine` | Pass |

## Representative cases

| ID | Expected | Actual | Result | Severity |
|----|----------|--------|--------|----------|
| SCH-001 | Random interval picks from configured 5–60 set | `pick_interval_minutes` covers all options over 200 draws | Pass | — |
| SCH-002 | User message reschedules `next_evaluation_at` | Scheduler sets future `next_evaluation_at` after inbound message | Pass | — |
| SCH-003 | Scan uses due users, not all enabled | `list_due` + worker scan | Pass | — |
| CAP-001 | v2 hourly cap blocks third send in 1h | `hourly_cap` reason | Pass | — |
| CAP-002 | Unanswered outbound blocks new sends | `awaiting_reply` | Pass | — |
| CTX-001 | Photography hobby detected in recent messages | `mentioned_hobbies` contains photography | Pass | — |
| ISO-001 | John gets photography brief, not Alex's car | Per-user memory isolation | Pass | — |
| QUIET-001 | Quiet hours block send (legacy gate) | `quiet_hours` in user TZ | Pass | — |

## Automated run

```
pytest tests/test_proactive_engine.py tests/test_proactive_engagement_v2.py -q
# 26 passed
```
