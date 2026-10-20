# Persona consistency QA

Automated QA for Sarah’s conversational persona: profile facts, memory, timeline, contradictions, proactive policy, formatting, and isolation.

The suite runs through the **real** LangGraph pipeline (`PersonaRuntime.run`). It does not replace the persona engine.

## Quick start

```powershell
cd e:\Persona
.\.venv\Scripts\Activate.ps1

# Seed suite definitions into the current Mongo DB (must be qa/test or mongomock)
python -m persona_runtime.qa seed --write-json

# Dry-run (no graph calls)
python -m persona_runtime.qa run --dry-run

# Run one case
python -m persona_runtime.qa run --test-key PROFILE-003

# Run a category
python -m persona_runtime.qa run --category persistent_memory

# Re-run failures from a prior run
python -m persona_runtime.qa run --failed-from <run_id>

# Compare two runs
python -m persona_runtime.qa compare <run_a> <run_b>
```

Offline CLI runs use `DeterministicQALLM` (no OpenAI). For live LLM judging:

```powershell
$env:QA_LLM = "live"
python -m persona_runtime.qa run --live-llm --test-key HUMAN-001
```

Reports are written under `qa_reports/` (gitignored) as JSON and Markdown.

An unfiltered run also refreshes repository-root `issues.md` (current summary plus a dated run-history section). Filtered runs (`--test-key`, `--category`, `--failed-from`) append history and leave the last full-suite summary in place. Live-LLM blocks and unresolved fact refs are filed as infrastructure, not persona defects.

## Safety

Before any write, the runner checks:

1. Database is mongomock, **or** `DB_NAME` / `QA_DB_NAME` contains `qa` or `test`.
2. Runtime persona/user ids start with `qa-`.
3. Cleanup deletes only those prefixes and never `sarah_taylor_001` / `local-user`.

`PersonaState` and `TimelineEvents` are persona-scoped. Every scenario therefore **clones** identity into a `qa-*` persona so production Sarah’s life state is not moved.

## Architecture

| Piece | Role |
|-------|------|
| `persona_runtime/qa/fixtures/definitions.py` | Canonical case definitions (also exported as JSON) |
| `seed.py` | Upserts `PersonaTestSuites` / cases / steps |
| `environment.py` | Clone persona, clock, reopen conversation, rebuild runtime, safe cleanup |
| `runner.py` | Multi-step scenarios against `PersonaRuntime` |
| `assertions.py` | Deterministic checks; LLM judge only when `QA_LLM=live` |
| `ledger.py` | Consistency ledger + contradiction timeline |
| `report.py` | Executive summary, issues, previous-run delta |
| `issues_md.py` | Root `issues.md` current summary and run history |

Mongo collections: `PersonaTestSuites`, `PersonaTestCases`, `PersonaTestSteps`, `PersonaTestRuns`, `PersonaTestResults`, `PersonaTestStepResults`, `PersonaTestIssues`.

## Adding a test without changing application code

1. Edit [`persona_runtime/qa/fixtures/definitions.py`](../persona_runtime/qa/fixtures/definitions.py) **or** the category JSON under `persona_runtime/qa/fixtures/`.
2. Prefer expected values as **fact refs**, not hard-coded fiction:

```json
{
  "type": "required_fact_present",
  "expected_ref": {"source": "canonical", "fact_id": "PERSONA_FACT_DOB"},
  "required": true
}
```

Other sources: `clock` (`field`), `world` (`path`), `habit` (`habit_id`), `transport`, `employment`, `literal`.

3. Re-seed:

```powershell
python -m persona_runtime.qa seed --write-json
```

4. Run the new key:

```powershell
python -m persona_runtime.qa run --test-key YOUR-KEY
```

Step actions available: `user_message`, `end_and_reopen_conversation`, `new_conversation_same_user`, `set_clock`, `advance_clock`, `rebuild_runtime`, `correct_canonical_fact`, `supersede_memory`, `set_proactive`, `schedule_resume`, `switch_user`, `set_persona_availability`, and isolation probes.

## Assertion statuses

| Status | Meaning |
|--------|---------|
| `pass` | Expectation met |
| `fail` | Product/fixture defect with evidence |
| `blocked` | Missing infra, dry-run, or live judge disabled |
| `not_applicable` | Optional check skipped |
| `needs_review` | Ambiguous LLM judge (confidence below threshold) |

**Policy:** never silently pass a required check when the response, memory trace, or state is unavailable — mark `blocked` or `fail`.

Live-only types (`tone_quality`, optional `topic_relevance`) are **blocked** in deterministic mode and are not release blockers.

## Memory assertions (separate)

- `memory_persisted` — document exists in Mongo with provenance
- `memory_retrieved` — id appears in `retrieved_memories` / `allowed_evidence_ids`
- `semantic_fact_match` — reply text uses the fact

A lucky reply without a stored memory fails `memory_persisted`.

## Modes

| Mode | How | LLM |
|------|-----|-----|
| Deterministic (default) | pytest / CLI without `--live-llm` | Stub / ScriptedLLM |
| Live judge | `QA_LLM=live` or `--live-llm` | OpenAI for open-ended quality |
| Dry-run | `--dry-run` | None; steps planned, assertions blocked |

## Limitations

- “Restart backend” = new `PersonaRuntime` on the same DB (no process kill).
- No user-facing memory delete API; “forget” tests use `status: superseded`.
- No named quiet-hours setting; `PROACTIVE-010` covers sleeping / low availability.
- `MemoryRetriever` recency uses injectable `utcnow()` (fixed for clock tests).
- `FORMAT-010` and `PERSIST-009` set a shared stub failure mode. The runner resets that mode at the start of every case.
- Offline generation speaks `ANSWER_PLAN` direct answers when the pipeline produced them, then the authoritative `CLOCK` block. It does not scan the whole persona dump for the first keyword.
- Language-quality cases are non-blocking when judged by an LLM.

## Pytest

```powershell
pytest tests/test_persona_qa_core.py -q
```

Covers seed load, isolation refusal, memory traces, clock injection, contradiction ledger, cleanup guard, reports, dry-run, and idempotency.
