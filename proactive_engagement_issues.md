# Proactive engagement — known issues

| ID | Severity | Issue | Notes |
|----|----------|-------|-------|
| PE-001 | Low | Stuck `running` ResponseJobs still block one-open-job index after worker crash | Pre-existing; no sweeper added |
| PE-002 | Low | No push/email delivery — polling UI only | By design |
| PE-003 | Medium | LLM decision cost scales with opted-in users × evaluation frequency | Mitigated by cheap gates + rule fallback |
| PE-004 | Low | Multi-instance workers may both evaluate same due user | Idempotent job insert + reschedule on skip |
| PE-005 | Info | Legacy `evaluate_proactive_policy` remains for QA only | Production uses `evaluate_outbound` |

## Open QA (manual / live LLM)

- Live OpenAI quality pass for `proactive_engagement_decision` not re-run in this pass.
- Browser verification of increased outbound frequency requires opted-in user + open UI.
