# Persona Capability Enforcement QA Report

Generated: 2026-11-03 (strict enforcement implementation)

## Architecture verified

- **Decision:** `capability_assessment` → LLM describe + `decide()` → `capability_blocked` for `OUTSIDE_DOMAIN` / `UNCERTAIN`
- **Bypass:** `generate_response` calls `emit_limitation_response()` — no `response_generation` LLM for blocked turns
- **Validation:** per-bubble `validate_capability_messages()`; blocked turns skip LLM repair and use templates on violation
- **Profiles:** Identity `capability_profile` with `restricted_domains`, `limitation_templates`, `general_assistant_mode=false`; missing profile uses `minimal_capability_profile()`

## Metrics (deterministic harness, CAP-001–022, mongomock + DeterministicQALLM)

| Metric | Result |
|---|---|
| Unsupported answer leakage (code/partial in blocked turns) | **0** in passing enforcement cases |
| Capability classification (offline `tests/test_capability.py`) | **27/27** pass |
| CAP suite eligible pass (excludes live-only `capability_judge`) | **20/22** pass, **2** fail (stub/isolation), **19** blocked judges |
| Adversarial bypass (CAP-016–019, CAP-022) | Pass on deterministic path |
| Cross-persona isolation (CAP-013) | Engineer step requires live or stub code generation — see issues |

## Regression spot-checks

| Test | Expected | Deterministic result |
|---|---|---|
| C++ table of 2 (Sarah) | Decline, no code | Pass (limitation path) |
| What is Python? (Sarah) | Decline, no tutorial | Pass |
| Variance analysis | Core answer | Category A (stub may use generic fallback — pre-existing QA stub) |
| Software engineer disclosure | Curiosity, not E | Pass after disclosure-only fix |
| Budget vs actual (CAP-021) | Core answer | Category A |

## Live OpenAI track

Not re-run in this pass. Run `scripts/qa_capability_track.py` with `QA_LLM=live` for release gating. **Unsupported leakage rate target: 0** on live CAP enforcement rows.

## Files

- `persona_runtime/capability/` — schemas, policy, validator, limitation, seed, profile
- `persona_runtime/graph/nodes.py` — bypass, blocked plan, validation, context updates
- `persona_runtime/qa/fixtures/definitions.py` — CAP-016–022
- `tests/test_capability.py` — policy, limitation, jailbreak tests
