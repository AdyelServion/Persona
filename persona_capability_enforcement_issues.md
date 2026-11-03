# Persona Capability Enforcement Issues

## Open

### CAP-012 — varied_declines under deterministic limitation templates

Multi-step specialist declines can repeat the same template line when the stub does not vary hash inputs enough. Production limitation pool excludes `recent_capability_declines`; re-verify on live OpenAI.

### CAP-013 — engineer persona step 3 with DeterministicQALLM

After `set_capability_profile` (software engineer), category **A** is expected for C++ artifacts. Offline stub may still surface engineer **fallback** wording instead of generated code; `capability_judge` is live-only. Re-run step 3 with live LLM or extend stub to emit sample code when `may_produce_artifacts` is true.

### Core-domain replies with DeterministicQALLM (CAP-001/002/004)

Some core-domain cases still receive generic stub text (`Yeah, fair enough.`) — pre-existing stub/answer-plan interaction, not capability bypass leakage.

## Closed in this implementation

- C++ verbal refusal + code leak (main LLM path bypassed for category E/U)
- Programming “what is X” treated as outside domain for Sarah (`restricted_domains`)
- User job disclosure alone no longer triggers restricted-domain block on the word “software”
- `repeated_capability_decline` no longer fails blocked limitation path validation

## Recommended next steps

1. Live run: `QA_DB_NAME=SarahQA python scripts/qa_capability_track.py`
2. Confirm **0** failures on CAP-005, CAP-006, CAP-016–020, CAP-022 with real model
3. Extend `DeterministicQALLM` to honor `may_produce_artifacts` for CAP-013 step 3 offline
