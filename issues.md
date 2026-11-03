# Persona QA issues

This file is generated from an executed QA run. Counts below are from that run. Unexecuted tests are not treated as passed.

## Run Information

- **Run ID:** `c9f8410a-c4dc-4fc8-b765-6886b85eac48`
- **Started:** 2026-11-02T07:17:22.046000 (UTC)
- **Completed:** 2026-11-02T07:20:00.733000 (UTC)
- **Timezone:** timestamps in this summary are UTC. Persona answers use the configured IANA zone (Europe/London for Sarah).
- **Environment:** qa
- **Tested persona:** qa-batch
- **Build:** dev
- **Model / provider:** gpt-4o-mini / openai
- **Prompt version:** not recorded
- **Live LLM judging:** False

## Execution Summary

- **Discovered / executed:** 164 / 164
- **Passed:** 121
- **Failed:** 0
- **Blocked:** 43
- **Skipped:** 0
- **Pass rate (executed, non-blocked):** 100.0% (121/121 non-blocked)
- **Commands:** Deterministic suite: `python -m persona_runtime.qa run` (mongomock or a database name containing `qa`/`test`; `DeterministicQALLM`, no live OpenAI). Existing regression: `pytest -q`. Run configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': False}`.

## Baseline failure disposition

Compared with run `dea14aee-aabc-4601-b522-566e99b6b98e` (21 failed, 90 passed, 39 blocked). Hometown remains Sheffield (`PERSONA_FACT_HOMETOWN`). Leeds is only the STATE-015 residence override.

| Test | Status | This run |
| --- | --- | --- |
| `CONTEXT-010` | Fixed and verified | passed |
| `CONTEXT-015` | Fixed and verified | passed |
| `FLOW-001` | Fixed and verified | passed |
| `FLOW-007` | Fixed and verified | passed |
| `FORMAT-002` | Fixed and verified | passed |
| `MEM-002` | Fixed and verified | passed |
| `MEM-004` | Fixed and verified | passed |
| `MEM-005` | Fixed and verified | passed |
| `MEM-006` | Fixed and verified | passed |
| `MEM-007` | Fixed and verified | passed |
| `MEM-008` | Fixed and verified | passed |
| `MEM-010` | Fixed and verified | passed |
| `MEM-012` | Fixed and verified | passed |
| `MEM-013` | Fixed and verified | passed |
| `PROFILE-004` | Fixed and verified | passed |
| `PROFILE-008` | Fixed and verified | passed |
| `PROFILE-014` | Fixed and verified | passed |
| `STATE-008` | Fixed and verified | passed |
| `STATE-014` | Fixed and verified | passed |
| `STATE-015` | Fixed and verified | passed |
| `UNKNOWN-009` | Fixed and verified | passed |

<!-- PYTEST -->
Pytest regression on 2026-10-20 (post-fix independent QA): `.venv311/Scripts/python.exe -m pytest -q --tb=line`. Result: 184 passed, 2 skipped in 140.59s. The two skips are the opt-in live naturalness eval (`RUN_LLM_EVAL`); that file targets `sarah_taylor_001` and was not enabled. No pytest failures.
<!-- /PYTEST -->

## Issues Found

No product-defect failures were recorded in the executed scope. Blocked and fixture problems are listed under Infrastructure/Test Problems and are not counted as confirmed persona defects.

## Memory and Consistency Findings

Ledger contradictions (confirmed by the consistency ledger, not by an LLM judge):

- `CONTEXT-010` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Manchester', 'source': 'response', 'timestamp': '2026-11-02T07:17:31.302277Z', 'confidence': 1.0, 'status': 'stated', 'conver… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-11-02T07:17:31.306026Z', 'confidence': 1.0, 'status': 'state…
- `CONTEXT-015` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-11-02T07:17:36.108536Z', 'confidence': 1.0, 'status': 'state… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Northbridge Financial Group', 'source': 'response', 'timestamp': '2026-11-02T07:17:36.108536Z', 'confidence': 1.0, 'status': …
- `CONTEXT-015` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Northbridge Financial Group', 'source': 'response', 'timestamp': '2026-11-02T07:17:36.108536Z', 'confidence': 1.0, 'status': … later={'subject': 'persona', 'attribute': 'fact', 'value': 'Manchester Finance Office, 18 Alderbrook Square, Manchester, UK', 'source': 'response', 'timestamp': '2026-11-02T07:17:36.108…
- `FLOW-001` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Manchester', 'source': 'response', 'timestamp': '2026-11-02T07:18:20.875266Z', 'confidence': 1.0, 'status': 'stated', 'conver… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-11-02T07:18:20.875266Z', 'confidence': 1.0, 'status': 'state…
- `FLOW-001` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-11-02T07:18:20.875266Z', 'confidence': 1.0, 'status': 'state… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Aries', 'source': 'response', 'timestamp': '2026-11-02T07:18:20.875266Z', 'confidence': 1.0, 'status': 'stated', 'conversatio…
- `FORMAT-002` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Manchester', 'source': 'response', 'timestamp': '2026-11-02T07:19:34.477147Z', 'confidence': 1.0, 'status': 'stated', 'conver… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-11-02T07:19:34.479149Z', 'confidence': 1.0, 'status': 'state…

## Timeline Findings

No failing timeline, date/time, or event-status assertions were recorded in this run.

## Infrastructure/Test Problems

### ISS-LIVE-LLM: Live semantic checks were not executed

- **Severity:** Needs Review
- **Category:** evaluation
- **Status:** Blocked
- **Classification:** blocked live-LLM check, not a persona defect
- **Affected tests:** `CONTEXT-001`, `CONTEXT-002`, `CONTEXT-003`, `CONTEXT-004`, `CONTEXT-005`, `CONTEXT-006`, `CONTEXT-007`, `CONTEXT-008`, `CONTEXT-009`, `CONTEXT-011`, `CONTEXT-012`, `EXTROVERT-002`, `FLOW-002`, `FLOW-004`, `FLOW-005`, `FLOW-006`, `FLOW-009`, `FORMAT-004`, `FORMAT-005`, `FORMAT-006`, `HUMAN-001`, `HUMAN-002`, `HUMAN-003`, `HUMAN-004`, `HUMAN-005`, `HUMAN-006`, `HUMAN-007`, `HUMAN-008`, `HUMAN-009`, `HUMAN-010`, `HUMAN-011`, `HUMAN-012`, `HUMAN-013`, `HUMAN-014`, `HUMAN-015`, `HUMAN-016`, `HUMAN-017`, `HUMAN-018`, `MEM-011`, `PROACTIVE-004`, `PROACTIVE-005`, `PROACTIVE-006`, `PROFILE-009`
- **Preconditions:** `QA_LLM` is not `live` and the run did not pass `--live-llm`.
- **Expected:** tone and optional topic checks run only with a live judge.
- **Actual:** those assertions returned `blocked` (`Live LLM evaluation disabled`). Required deterministic checks on the same cases are reflected in the case status; a case listed here had no product-defect failure.
- **Suspected root cause:** Hypothesis: opt-in live judging was not enabled for this run.
- **Recommended fix:** Re-run the listed keys with `QA_LLM=live` when an OpenAI key is available. Do not treat this block as a pass.

## Fixed and Re-tested Issues

No previously failing tests were recorded as newly passing in this run.

## Remaining Risks and Next Actions

- No probable product defects were opened from this run.
- 43 case(s) are blocked on live LLM judging and must not be read as passes.
- This run used the deterministic stub. It exercises the real LangGraph pipeline with scripted model output, not production OpenAI variability.
- Do not point the suite at database `Sarah` or persona `sarah_taylor_001`. Cleanup is limited to `qa-` ids.

<!-- RUN_HISTORY -->
<!-- run:e77d6173-a8c1-4852-9023-afe3a1ee309b -->
### Run `e77d6173-a8c1-4852-9023-afe3a1ee309b` — 2026-10-19T13:24:47.319000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/e77d6173-a8c1-4852-9023-afe3a1ee309b.json`

<!-- run:5240ffd8-092a-4515-b8a0-7e830a64a78c -->
### Run `5240ffd8-092a-4515-b8a0-7e830a64a78c` — 2026-10-19T13:24:58.023000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/5240ffd8-092a-4515-b8a0-7e830a64a78c.json`

<!-- run:29bc066b-dea0-42f3-9129-b9c07703aba5 -->
### Run `29bc066b-dea0-42f3-9129-b9c07703aba5` — 2026-10-19T13:25:00.675000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/29bc066b-dea0-42f3-9129-b9c07703aba5.json`

<!-- run:f02871dd-b857-42bc-b91f-e428fcf49dc7 -->
### Run `f02871dd-b857-42bc-b91f-e428fcf49dc7` — 2026-10-19T13:30:02.437000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 74 / 37 / 39 / 0 (total 150)
- Pass rate (non-blocked): 66.67% (74/111 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': False}`
- Report: `qa_reports/f02871dd-b857-42bc-b91f-e428fcf49dc7.json`

<!-- run:d6e9935f-bbd1-4d5b-b910-19515a20d16f -->
### Run `d6e9935f-bbd1-4d5b-b910-19515a20d16f` — 2026-10-19T13:37:39.876000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 90 / 21 / 39 / 0 (total 150)
- Pass rate (non-blocked): 81.08% (90/111 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': False}`
- Report: `qa_reports/d6e9935f-bbd1-4d5b-b910-19515a20d16f.json`

<!-- run:dea14aee-aabc-4601-b522-566e99b6b98e -->
### Run `dea14aee-aabc-4601-b522-566e99b6b98e` — 2026-10-19T13:43:02.150000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 90 / 21 / 39 / 0 (total 150)
- Pass rate (non-blocked): 81.08% (90/111 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': False}`
- Report: `qa_reports/dea14aee-aabc-4601-b522-566e99b6b98e.json`

<!-- run:6b247f3d-ec50-47c5-afa9-33f944913d19 -->
### Run `6b247f3d-ec50-47c5-afa9-33f944913d19` — 2026-10-19T13:45:35.474000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/6b247f3d-ec50-47c5-afa9-33f944913d19.json`

<!-- run:edc20837-0e9b-49a5-9d95-0fb74d7906d2 -->
### Run `edc20837-0e9b-49a5-9d95-0fb74d7906d2` — 2026-10-19T13:45:46.992000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/edc20837-0e9b-49a5-9d95-0fb74d7906d2.json`

<!-- run:1f221b79-7a62-41c0-9175-402a526df476 -->
### Run `1f221b79-7a62-41c0-9175-402a526df476` — 2026-10-19T13:45:49.641000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/1f221b79-7a62-41c0-9175-402a526df476.json`

<!-- run:9071b1ed-de74-4017-8200-d7e13014b0ff -->
### Run `9071b1ed-de74-4017-8200-d7e13014b0ff` — 2026-10-19T14:22:46.506000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/9071b1ed-de74-4017-8200-d7e13014b0ff.json`

<!-- run:f56b887f-2664-4626-ae0d-69e6a1674850 -->
### Run `f56b887f-2664-4626-ae0d-69e6a1674850` — 2026-10-19T14:22:56.695000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/f56b887f-2664-4626-ae0d-69e6a1674850.json`

<!-- run:99dc3af0-120e-4501-aa3a-9b5f295fa35e -->
### Run `99dc3af0-120e-4501-aa3a-9b5f295fa35e` — 2026-10-19T14:22:59.301000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/99dc3af0-120e-4501-aa3a-9b5f295fa35e.json`

<!-- run:711fea9b-d185-4a3b-ac73-a051f4518309 -->
### Run `711fea9b-d185-4a3b-ac73-a051f4518309` — 2026-10-19T14:26:30.275000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 111 / 0 / 39 / 0 (total 150)
- Pass rate (non-blocked): 100.0% (111/111 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': False}`
- Report: `qa_reports/711fea9b-d185-4a3b-ac73-a051f4518309.json`

<!-- run:896c4527-68eb-4ed8-a7c4-7fb70570c261 -->
### Run `896c4527-68eb-4ed8-a7c4-7fb70570c261` — 2026-10-20T07:30:57.382000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/896c4527-68eb-4ed8-a7c4-7fb70570c261.json`

<!-- run:ff59c412-5ab7-44d0-ae61-4147c1a54c1c -->
### Run `ff59c412-5ab7-44d0-ae61-4147c1a54c1c` — 2026-10-20T07:31:07.557000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/ff59c412-5ab7-44d0-ae61-4147c1a54c1c.json`

<!-- run:9197a687-2cbb-4fa1-8a56-acb50322b187 -->
### Run `9197a687-2cbb-4fa1-8a56-acb50322b187` — 2026-10-20T07:31:10.062000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/9197a687-2cbb-4fa1-8a56-acb50322b187.json`

<!-- run:f78580dd-9814-4ce9-8ba8-022f92643ab4 -->
### Run `f78580dd-9814-4ce9-8ba8-022f92643ab4` — 2026-10-20T07:49:48.269000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/f78580dd-9814-4ce9-8ba8-022f92643ab4.json`

<!-- run:cefde60d-4c95-46b7-a876-6bd44f37cc1b -->
### Run `cefde60d-4c95-46b7-a876-6bd44f37cc1b` — 2026-10-20T07:49:59.080000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/cefde60d-4c95-46b7-a876-6bd44f37cc1b.json`

<!-- run:5bea6cb3-ab1c-420a-b03a-0c18219670b9 -->
### Run `5bea6cb3-ab1c-420a-b03a-0c18219670b9` — 2026-10-20T07:50:01.739000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/5bea6cb3-ab1c-420a-b03a-0c18219670b9.json`

<!-- run:d79303e5-6e04-450a-bf92-2394488e42ad -->
### Run `d79303e5-6e04-450a-bf92-2394488e42ad` — 2026-10-20T08:05:26.415000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 111 / 0 / 42 / 0 (total 153)
- Pass rate (non-blocked): 100.0% (111/111 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': False}`
- Report: `qa_reports/d79303e5-6e04-450a-bf92-2394488e42ad.json`

<!-- run:cb71a460-88ce-40a9-bedb-efd3b21b54c6 -->
### Run `cb71a460-88ce-40a9-bedb-efd3b21b54c6` — 2026-10-20T08:16:07.081000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 34 / 4 / 1 / 0 (total 39)
- Pass rate (non-blocked): 89.47% (34/38 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/cb71a460-88ce-40a9-bedb-efd3b21b54c6.json`

<!-- run:d44bb44d-521c-4b86-a4bd-6601bab62a16 -->
### Run `d44bb44d-521c-4b86-a4bd-6601bab62a16` — 2026-10-20T08:35:23.456000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 25 / 4 / 0 / 0 (total 29)
- Pass rate (non-blocked): 86.21% (25/29 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/d44bb44d-521c-4b86-a4bd-6601bab62a16.json`

<!-- run:70dadc5d-6acf-4773-a15c-43226a90fa0e -->
### Run `70dadc5d-6acf-4773-a15c-43226a90fa0e` — 2026-10-20T08:42:18.704000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 13 / 5 / 0 / 0 (total 18)
- Pass rate (non-blocked): 72.22% (13/18 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/70dadc5d-6acf-4773-a15c-43226a90fa0e.json`

<!-- run:a9a6a5e3-c86a-4a3f-b217-5baf17948456 -->
### Run `a9a6a5e3-c86a-4a3f-b217-5baf17948456` — 2026-10-20T08:49:02.430000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 14 / 4 / 0 / 0 (total 18)
- Pass rate (non-blocked): 77.78% (14/18 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/a9a6a5e3-c86a-4a3f-b217-5baf17948456.json`

<!-- run:33f7ffaa-5842-4add-a79f-0389803cb88b -->
### Run `33f7ffaa-5842-4add-a79f-0389803cb88b` — 2026-10-20T08:55:39.674000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 15 / 3 / 0 / 0 (total 18)
- Pass rate (non-blocked): 83.33% (15/18 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/33f7ffaa-5842-4add-a79f-0389803cb88b.json`

<!-- run:75d3aa2a-0d8f-4c68-8d18-91779f15ba15 -->
### Run `75d3aa2a-0d8f-4c68-8d18-91779f15ba15` — 2026-10-20T10:06:34.254000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 109 / 2 / 42 / 0 (total 153)
- Pass rate (non-blocked): 98.2% (109/111 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': False}`
- Report: `qa_reports/75d3aa2a-0d8f-4c68-8d18-91779f15ba15.json`

<!-- run:d330bbe0-c12d-4982-aa66-7093078b826e -->
### Run `d330bbe0-c12d-4982-aa66-7093078b826e` — 2026-10-26T06:47:22.954000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/d330bbe0-c12d-4982-aa66-7093078b826e.json`

<!-- run:75a4d26d-cdb2-4619-8fd9-8430e402c193 -->
### Run `75a4d26d-cdb2-4619-8fd9-8430e402c193` — 2026-10-26T06:47:34.494000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/75a4d26d-cdb2-4619-8fd9-8430e402c193.json`

<!-- run:8481c8f4-d90a-4335-826b-05cc5711842f -->
### Run `8481c8f4-d90a-4335-826b-05cc5711842f` — 2026-10-26T06:47:37.494000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/8481c8f4-d90a-4335-826b-05cc5711842f.json`

<!-- run:8e26ba3c-8d59-4668-97d1-02635a8f1829 -->
### Run `8e26ba3c-8d59-4668-97d1-02635a8f1829` — 2026-11-02T06:28:36.051000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/8e26ba3c-8d59-4668-97d1-02635a8f1829.json`

<!-- run:13b299d0-4882-4611-98c8-01c05611cc4d -->
### Run `13b299d0-4882-4611-98c8-01c05611cc4d` — 2026-11-02T06:28:47.145000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/13b299d0-4882-4611-98c8-01c05611cc4d.json`

<!-- run:633ca162-e5e1-4288-b960-ed1bfb6f1b8f -->
### Run `633ca162-e5e1-4288-b960-ed1bfb6f1b8f` — 2026-11-02T06:28:49.948000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/633ca162-e5e1-4288-b960-ed1bfb6f1b8f.json`

<!-- run:c91888a4-f925-4aa7-8898-2dac45efc0ab -->
### Run `c91888a4-f925-4aa7-8898-2dac45efc0ab` — 2026-11-02T06:49:27.493000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/c91888a4-f925-4aa7-8898-2dac45efc0ab.json`

<!-- run:3b6b4f1f-09fd-4236-81c4-a5278fa8669b -->
### Run `3b6b4f1f-09fd-4236-81c4-a5278fa8669b` — 2026-11-02T06:49:38.301000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/3b6b4f1f-09fd-4236-81c4-a5278fa8669b.json`

<!-- run:c52c5398-d4fe-46e3-b8ab-d402c278a51a -->
### Run `c52c5398-d4fe-46e3-b8ab-d402c278a51a` — 2026-11-02T06:49:40.988000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/c52c5398-d4fe-46e3-b8ab-d402c278a51a.json`

<!-- run:2526e398-c550-4d59-8c5c-7abd20a53d0e -->
### Run `2526e398-c550-4d59-8c5c-7abd20a53d0e` — 2026-11-02T06:59:12.578000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/2526e398-c550-4d59-8c5c-7abd20a53d0e.json`

<!-- run:c22c290c-2fc8-4bec-abd6-ebc151d4d093 -->
### Run `c22c290c-2fc8-4bec-abd6-ebc151d4d093` — 2026-11-02T06:59:23.639000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/c22c290c-2fc8-4bec-abd6-ebc151d4d093.json`

<!-- run:ca446c08-6f85-45ad-98cc-63b96c47ac20 -->
### Run `ca446c08-6f85-45ad-98cc-63b96c47ac20` — 2026-11-02T06:59:26.408000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/ca446c08-6f85-45ad-98cc-63b96c47ac20.json`

<!-- run:f59fbb3a-1cf7-4534-9a37-2fdf5372fbbe -->
### Run `f59fbb3a-1cf7-4534-9a37-2fdf5372fbbe` — 2026-11-02T07:01:33.625000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/f59fbb3a-1cf7-4534-9a37-2fdf5372fbbe.json`

<!-- run:ab5ad9cc-b366-4bf9-87d2-0d4d856b0f64 -->
### Run `ab5ad9cc-b366-4bf9-87d2-0d4d856b0f64` — 2026-11-02T07:01:44.707000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/ab5ad9cc-b366-4bf9-87d2-0d4d856b0f64.json`

<!-- run:62a58b33-9d61-419c-92fe-92b5d4b44a12 -->
### Run `62a58b33-9d61-419c-92fe-92b5d4b44a12` — 2026-11-02T07:01:47.642000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/62a58b33-9d61-419c-92fe-92b5d4b44a12.json`

<!-- run:a4e34fab-f2e1-4b0d-b0d4-50ad6b6e289e -->
### Run `a4e34fab-f2e1-4b0d-b0d4-50ad6b6e289e` — 2026-11-02T07:11:37.853000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 3 / 0 / 0 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (3/3 non-blocked)
- Configuration: `{'category': 'multi_user_isolation', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/a4e34fab-f2e1-4b0d-b0d4-50ad6b6e289e.json`

<!-- run:e14c0aa1-b5bb-4230-a6e7-2b70e38eb9c6 -->
### Run `e14c0aa1-b5bb-4230-a6e7-2b70e38eb9c6` — 2026-11-02T07:11:42.480000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/e14c0aa1-b5bb-4230-a6e7-2b70e38eb9c6.json`

<!-- run:69547fc2-13d9-4570-a58f-9edc345214aa -->
### Run `69547fc2-13d9-4570-a58f-9edc345214aa` — 2026-11-02T07:11:49.418000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 4 / 1 / 0 / 0 (total 5)
- Pass rate (non-blocked): 80.0% (4/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/69547fc2-13d9-4570-a58f-9edc345214aa.json`

<!-- run:c79b1171-40ef-4aa4-9f1b-ce55d94b7eb8 -->
### Run `c79b1171-40ef-4aa4-9f1b-ce55d94b7eb8` — 2026-11-02T07:12:10.835000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 4 / 1 / 0 / 0 (total 5)
- Pass rate (non-blocked): 80.0% (4/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/c79b1171-40ef-4aa4-9f1b-ce55d94b7eb8.json`

<!-- run:65157155-d336-4a47-b373-27b8bf7e63ee -->
### Run `65157155-d336-4a47-b373-27b8bf7e63ee` — 2026-11-02T07:12:27.397000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 4 / 1 / 0 / 0 (total 5)
- Pass rate (non-blocked): 80.0% (4/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/65157155-d336-4a47-b373-27b8bf7e63ee.json`

<!-- run:37e5b587-67db-45ae-aecc-21d803a47bcb -->
### Run `37e5b587-67db-45ae-aecc-21d803a47bcb` — 2026-11-02T07:12:34.242000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/37e5b587-67db-45ae-aecc-21d803a47bcb.json`

<!-- run:7e971bb6-5be8-4e8c-b63e-6b66cc427b7c -->
### Run `7e971bb6-5be8-4e8c-b63e-6b66cc427b7c` — 2026-11-02T07:13:13.905000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 3 / 0 / 0 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (3/3 non-blocked)
- Configuration: `{'category': 'multi_user_isolation', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/7e971bb6-5be8-4e8c-b63e-6b66cc427b7c.json`

<!-- run:230862cb-3b3c-48ee-b2f2-9c4a6fa03d52 -->
### Run `230862cb-3b3c-48ee-b2f2-9c4a6fa03d52` — 2026-11-02T07:13:18.577000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/230862cb-3b3c-48ee-b2f2-9c4a6fa03d52.json`

<!-- run:78b2e5ad-6cc9-45cb-9ab3-92d191ad1f42 -->
### Run `78b2e5ad-6cc9-45cb-9ab3-92d191ad1f42` — 2026-11-02T07:13:25.015000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 5 / 0 / 0 / 0 (total 5)
- Pass rate (non-blocked): 100.0% (5/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/78b2e5ad-6cc9-45cb-9ab3-92d191ad1f42.json`

<!-- run:26d095cf-620a-4db0-80bb-69b711524de7 -->
### Run `26d095cf-620a-4db0-80bb-69b711524de7` — 2026-11-02T07:15:48.386000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/26d095cf-620a-4db0-80bb-69b711524de7.json`

<!-- run:6d8a9ea1-4a07-418d-a9d0-84fd98721483 -->
### Run `6d8a9ea1-4a07-418d-a9d0-84fd98721483` — 2026-11-02T07:15:59.226000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/6d8a9ea1-4a07-418d-a9d0-84fd98721483.json`

<!-- run:2ad1e628-f3e3-473e-a9cc-47d3dda49839 -->
### Run `2ad1e628-f3e3-473e-a9cc-47d3dda49839` — 2026-11-02T07:16:01.892000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/2ad1e628-f3e3-473e-a9cc-47d3dda49839.json`

<!-- run:e37f38b2-dbbe-4589-ae18-5e5efa701a8b -->
### Run `e37f38b2-dbbe-4589-ae18-5e5efa701a8b` — 2026-11-02T07:16:26.366000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 3 / 0 / 0 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (3/3 non-blocked)
- Configuration: `{'category': 'multi_user_isolation', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/e37f38b2-dbbe-4589-ae18-5e5efa701a8b.json`

<!-- run:a03afc1a-1266-459d-9e4a-73cfa1a7f639 -->
### Run `a03afc1a-1266-459d-9e4a-73cfa1a7f639` — 2026-11-02T07:16:30.951000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/a03afc1a-1266-459d-9e4a-73cfa1a7f639.json`

<!-- run:51546ed6-26e0-4282-a128-e00651127061 -->
### Run `51546ed6-26e0-4282-a128-e00651127061` — 2026-11-02T07:16:37.370000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 5 / 0 / 0 / 0 (total 5)
- Pass rate (non-blocked): 100.0% (5/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/51546ed6-26e0-4282-a128-e00651127061.json`

<!-- run:c9f8410a-c4dc-4fc8-b765-6886b85eac48 -->
### Run `c9f8410a-c4dc-4fc8-b765-6886b85eac48` — 2026-11-02T07:20:00.733000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 121 / 0 / 43 / 0 (total 164)
- Pass rate (non-blocked): 100.0% (121/121 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': False}`
- Report: `qa_reports/c9f8410a-c4dc-4fc8-b765-6886b85eac48.json`

<!-- run:ba20f03e-e5fb-4411-8f11-a0774e8820cc -->
### Run `ba20f03e-e5fb-4411-8f11-a0774e8820cc` — 2026-11-02T07:21:47.099000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 3 / 0 / 0 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (3/3 non-blocked)
- Configuration: `{'category': 'multi_user_isolation', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/ba20f03e-e5fb-4411-8f11-a0774e8820cc.json`

<!-- run:eb2a0d18-2ef7-4ce1-a8b1-8bf833e69749 -->
### Run `eb2a0d18-2ef7-4ce1-a8b1-8bf833e69749` — 2026-11-02T07:21:51.381000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/eb2a0d18-2ef7-4ce1-a8b1-8bf833e69749.json`

<!-- run:212417e8-3377-47fc-8fd3-cd5f8f30b8f6 -->
### Run `212417e8-3377-47fc-8fd3-cd5f8f30b8f6` — 2026-11-02T07:21:57.853000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 5 / 0 / 0 / 0 (total 5)
- Pass rate (non-blocked): 100.0% (5/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/212417e8-3377-47fc-8fd3-cd5f8f30b8f6.json`

<!-- run:35b93092-3a3d-44a8-be64-a2c4440e025e -->
### Run `35b93092-3a3d-44a8-be64-a2c4440e025e` — 2026-11-02T07:25:54.222000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/35b93092-3a3d-44a8-be64-a2c4440e025e.json`

<!-- run:9e347d01-dc38-4438-a4ff-3da195e32507 -->
### Run `9e347d01-dc38-4438-a4ff-3da195e32507` — 2026-11-02T07:26:04.581000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/9e347d01-dc38-4438-a4ff-3da195e32507.json`

<!-- run:ea6027d5-aa15-46ed-b8b0-88d9631e2b6e -->
### Run `ea6027d5-aa15-46ed-b8b0-88d9631e2b6e` — 2026-11-02T07:26:07.232000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/ea6027d5-aa15-46ed-b8b0-88d9631e2b6e.json`

<!-- run:2fc6925f-4b13-4784-b293-c2be7baf38fc -->
### Run `2fc6925f-4b13-4784-b293-c2be7baf38fc` — 2026-11-02T07:26:32.950000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 3 / 0 / 0 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (3/3 non-blocked)
- Configuration: `{'category': 'multi_user_isolation', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/2fc6925f-4b13-4784-b293-c2be7baf38fc.json`

<!-- run:7bfa82f3-1f01-480e-9c05-46013d5f3bc0 -->
### Run `7bfa82f3-1f01-480e-9c05-46013d5f3bc0` — 2026-11-02T07:26:37.474000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/7bfa82f3-1f01-480e-9c05-46013d5f3bc0.json`

<!-- run:42ff3b8a-fafc-439f-a3c1-737808510e32 -->
### Run `42ff3b8a-fafc-439f-a3c1-737808510e32` — 2026-11-02T07:26:43.765000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 5 / 0 / 0 / 0 (total 5)
- Pass rate (non-blocked): 100.0% (5/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/42ff3b8a-fafc-439f-a3c1-737808510e32.json`

<!-- run:f8aa5d87-a327-4b82-8a8a-172369e9d3d4 -->
### Run `f8aa5d87-a327-4b82-8a8a-172369e9d3d4` — 2026-11-02T08:59:40.373000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/f8aa5d87-a327-4b82-8a8a-172369e9d3d4.json`

<!-- run:5fc187d5-f598-43fb-8f78-e0bc59169a4e -->
### Run `5fc187d5-f598-43fb-8f78-e0bc59169a4e` — 2026-11-02T08:59:51.551000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/5fc187d5-f598-43fb-8f78-e0bc59169a4e.json`

<!-- run:29632102-793d-4db7-bc1b-25d1dc389fcc -->
### Run `29632102-793d-4db7-bc1b-25d1dc389fcc` — 2026-11-02T08:59:54.635000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/29632102-793d-4db7-bc1b-25d1dc389fcc.json`

<!-- run:d66a643d-1265-469f-b642-125b9eae95e1 -->
### Run `d66a643d-1265-469f-b642-125b9eae95e1` — 2026-11-02T09:00:23.110000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 3 / 0 / 0 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (3/3 non-blocked)
- Configuration: `{'category': 'multi_user_isolation', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/d66a643d-1265-469f-b642-125b9eae95e1.json`

<!-- run:fa0fd1d2-7254-4dee-88d3-14088912665f -->
### Run `fa0fd1d2-7254-4dee-88d3-14088912665f` — 2026-11-02T09:00:28.160000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/fa0fd1d2-7254-4dee-88d3-14088912665f.json`

<!-- run:59676280-aae4-4dc9-8872-6103f04c444f -->
### Run `59676280-aae4-4dc9-8872-6103f04c444f` — 2026-11-02T09:00:35.267000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 5 / 0 / 0 / 0 (total 5)
- Pass rate (non-blocked): 100.0% (5/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/59676280-aae4-4dc9-8872-6103f04c444f.json`

<!-- run:d53d8a46-e84b-4001-9960-430131826e61 -->
### Run `d53d8a46-e84b-4001-9960-430131826e61` — 2026-11-02T13:10:23.419000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/d53d8a46-e84b-4001-9960-430131826e61.json`

<!-- run:3c446814-63bb-4971-b5d8-feb06b1e10ae -->
### Run `3c446814-63bb-4971-b5d8-feb06b1e10ae` — 2026-11-02T13:10:34.722000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/3c446814-63bb-4971-b5d8-feb06b1e10ae.json`

<!-- run:0b6c7942-3276-46ca-b996-f22e5902eafe -->
### Run `0b6c7942-3276-46ca-b996-f22e5902eafe` — 2026-11-02T13:10:37.461000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/0b6c7942-3276-46ca-b996-f22e5902eafe.json`

<!-- run:ffbd0668-6365-489c-a77a-7713f3392270 -->
### Run `ffbd0668-6365-489c-a77a-7713f3392270` — 2026-11-02T13:12:17.533000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 3 / 0 / 0 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (3/3 non-blocked)
- Configuration: `{'category': 'multi_user_isolation', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/ffbd0668-6365-489c-a77a-7713f3392270.json`

<!-- run:288606d9-f7bd-4438-a760-49535ff46139 -->
### Run `288606d9-f7bd-4438-a760-49535ff46139` — 2026-11-02T13:12:22.434000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/288606d9-f7bd-4438-a760-49535ff46139.json`

<!-- run:365efa8d-e240-444e-96c9-93f7c55b578b -->
### Run `365efa8d-e240-444e-96c9-93f7c55b578b` — 2026-11-02T13:12:29.156000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 5 / 0 / 0 / 0 (total 5)
- Pass rate (non-blocked): 100.0% (5/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/365efa8d-e240-444e-96c9-93f7c55b578b.json`

<!-- run:d565e304-96ef-4050-bc3d-6e7d10bfffb9 -->
### Run `d565e304-96ef-4050-bc3d-6e7d10bfffb9` — 2026-11-02T13:15:59.999000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/d565e304-96ef-4050-bc3d-6e7d10bfffb9.json`

<!-- run:4144785e-60ec-4f05-9192-b12562652fc9 -->
### Run `4144785e-60ec-4f05-9192-b12562652fc9` — 2026-11-02T13:16:10.726000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/4144785e-60ec-4f05-9192-b12562652fc9.json`

<!-- run:fe6913dd-1623-4e93-8487-548331e4f97e -->
### Run `fe6913dd-1623-4e93-8487-548331e4f97e` — 2026-11-02T13:16:13.460000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/fe6913dd-1623-4e93-8487-548331e4f97e.json`

<!-- run:2649b850-9285-4bde-af29-9748560be54e -->
### Run `2649b850-9285-4bde-af29-9748560be54e` — 2026-11-02T13:17:04.302000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 3 / 0 / 0 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (3/3 non-blocked)
- Configuration: `{'category': 'multi_user_isolation', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/2649b850-9285-4bde-af29-9748560be54e.json`

<!-- run:b18bba48-ac25-429d-bc47-9dae10e1340f -->
### Run `b18bba48-ac25-429d-bc47-9dae10e1340f` — 2026-11-02T13:17:09.240000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/b18bba48-ac25-429d-bc47-9dae10e1340f.json`

<!-- run:cba75dfd-8cb7-47e8-b957-3bfb66279441 -->
### Run `cba75dfd-8cb7-47e8-b957-3bfb66279441` — 2026-11-02T13:17:15.863000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 5 / 0 / 0 / 0 (total 5)
- Pass rate (non-blocked): 100.0% (5/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/cba75dfd-8cb7-47e8-b957-3bfb66279441.json`

<!-- run:aa4ca547-0a72-4a76-a8c9-bceb4f76501c -->
### Run `aa4ca547-0a72-4a76-a8c9-bceb4f76501c` — 2026-11-02T13:27:36.754000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 16 / 6 / 0 / 0 (total 22)
- Pass rate (non-blocked): 72.73% (16/22 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/aa4ca547-0a72-4a76-a8c9-bceb4f76501c.json`

<!-- run:d852daf3-c12d-4e36-ab2a-f528e676988d -->
### Run `d852daf3-c12d-4e36-ab2a-f528e676988d` — 2026-11-02T13:37:59.159000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 10 / 5 / 0 / 0 (total 15)
- Pass rate (non-blocked): 66.67% (10/15 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/d852daf3-c12d-4e36-ab2a-f528e676988d.json`

<!-- run:eea6689c-1f81-4588-8ee7-a3285b1d31eb -->
### Run `eea6689c-1f81-4588-8ee7-a3285b1d31eb` — 2026-11-02T13:40:46.898000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/eea6689c-1f81-4588-8ee7-a3285b1d31eb.json`

<!-- run:bd0f1deb-7002-4dba-8856-c85cda292c87 -->
### Run `bd0f1deb-7002-4dba-8856-c85cda292c87` — 2026-11-02T13:40:57.571000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/bd0f1deb-7002-4dba-8856-c85cda292c87.json`

<!-- run:55cccc05-4157-4f02-988a-de87306b4801 -->
### Run `55cccc05-4157-4f02-988a-de87306b4801` — 2026-11-02T13:41:00.287000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/55cccc05-4157-4f02-988a-de87306b4801.json`

<!-- run:85f379f6-16f6-4c2d-815f-aecb12418c9c -->
### Run `85f379f6-16f6-4c2d-815f-aecb12418c9c` — 2026-11-02T13:51:56.439000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 21 / 1 / 0 / 0 (total 22)
- Pass rate (non-blocked): 95.45% (21/22 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/85f379f6-16f6-4c2d-815f-aecb12418c9c.json`

<!-- run:fd4b70be-7e06-45bc-988b-eb239160d58d -->
### Run `fd4b70be-7e06-45bc-988b-eb239160d58d` — 2026-11-02T13:52:10.518000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/fd4b70be-7e06-45bc-988b-eb239160d58d.json`

<!-- run:9747aa66-4629-4b1a-a1ef-21df90cfdd0c -->
### Run `9747aa66-4629-4b1a-a1ef-21df90cfdd0c` — 2026-11-02T13:52:21.115000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/9747aa66-4629-4b1a-a1ef-21df90cfdd0c.json`

<!-- run:e9a67554-6f95-4225-a2d0-0842908bf750 -->
### Run `e9a67554-6f95-4225-a2d0-0842908bf750` — 2026-11-02T13:52:23.741000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/e9a67554-6f95-4225-a2d0-0842908bf750.json`

<!-- run:805c1a73-ae86-4f11-bd9b-b180cde95cbf -->
### Run `805c1a73-ae86-4f11-bd9b-b180cde95cbf` — 2026-11-02T13:58:50.621000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 6 / 1 / 0 / 0 (total 7)
- Pass rate (non-blocked): 85.71% (6/7 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/805c1a73-ae86-4f11-bd9b-b180cde95cbf.json`

<!-- run:bb27a09d-9c00-4620-a629-eb1c13ff677d -->
### Run `bb27a09d-9c00-4620-a629-eb1c13ff677d` — 2026-11-02T14:00:03.333000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/bb27a09d-9c00-4620-a629-eb1c13ff677d.json`

<!-- run:d5d3c4df-11a7-429f-b74e-1a3a0e4e02c1 -->
### Run `d5d3c4df-11a7-429f-b74e-1a3a0e4e02c1` — 2026-11-02T14:00:13.839000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/d5d3c4df-11a7-429f-b74e-1a3a0e4e02c1.json`

<!-- run:a7dc27d5-3707-4476-8d4d-04ba3df698ac -->
### Run `a7dc27d5-3707-4476-8d4d-04ba3df698ac` — 2026-11-02T14:00:16.453000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/a7dc27d5-3707-4476-8d4d-04ba3df698ac.json`

<!-- run:f7f83a3d-d016-4736-a99d-c5d339737741 -->
### Run `f7f83a3d-d016-4736-a99d-c5d339737741` — 2026-11-02T14:00:39.572000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 1 / 0 / 0 (total 1)
- Pass rate (non-blocked): 0.0% (0/1 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/f7f83a3d-d016-4736-a99d-c5d339737741.json`

<!-- run:4df6d44e-63cf-4827-9c77-1da79631d660 -->
### Run `4df6d44e-63cf-4827-9c77-1da79631d660` — 2026-11-02T14:01:21.135000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/4df6d44e-63cf-4827-9c77-1da79631d660.json`

<!-- run:2cec4730-303d-47e5-a8f1-89a4c643570f -->
### Run `2cec4730-303d-47e5-a8f1-89a4c643570f` — 2026-11-02T14:13:22.384000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'PROFILE-003', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/2cec4730-303d-47e5-a8f1-89a4c643570f.json`

<!-- run:2f5f55d7-86a4-4783-b8ea-1fed0a044b88 -->
### Run `2f5f55d7-86a4-4783-b8ea-1fed0a044b88` — 2026-11-02T14:13:34.842000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 0 / 0 / 1 / 0 (total 1)
- Pass rate (non-blocked): n/a (no executed non-blocked tests)
- Configuration: `{'category': None, 'test_key': 'FORMAT-001', 'failed_from': None, 'dry_run': True, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/2f5f55d7-86a4-4783-b8ea-1fed0a044b88.json`

<!-- run:33cb0f33-66fd-4465-9a1b-46b857497e28 -->
### Run `33cb0f33-66fd-4465-9a1b-46b857497e28` — 2026-11-02T14:13:37.745000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 0 / 0 / 0 (total 1)
- Pass rate (non-blocked): 100.0% (1/1 non-blocked)
- Configuration: `{'category': None, 'test_key': 'FORMAT-007', 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/33cb0f33-66fd-4465-9a1b-46b857497e28.json`

<!-- run:85b007b4-8e7d-4e5c-87ad-cb1ff000fa9c -->
### Run `85b007b4-8e7d-4e5c-87ad-cb1ff000fa9c` — 2026-11-02T14:14:31.483000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 24 / 0 / 0 / 0 (total 24)
- Pass rate (non-blocked): 100.0% (24/24 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/85b007b4-8e7d-4e5c-87ad-cb1ff000fa9c.json`

<!-- run:ed952c6c-3c4f-4863-9f61-9e2746d89959 -->
### Run `ed952c6c-3c4f-4863-9f61-9e2746d89959` — 2026-11-02T14:15:32.223000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 3 / 0 / 0 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (3/3 non-blocked)
- Configuration: `{'category': 'multi_user_isolation', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/ed952c6c-3c4f-4863-9f61-9e2746d89959.json`

<!-- run:c9eeb473-bdb0-44a6-bc4a-bf0e617043ba -->
### Run `c9eeb473-bdb0-44a6-bc4a-bf0e617043ba` — 2026-11-02T14:15:37.375000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 2 / 0 / 1 / 0 (total 3)
- Pass rate (non-blocked): 100.0% (2/2 non-blocked)
- Configuration: `{'category': 'extrovert_engagement', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/c9eeb473-bdb0-44a6-bc4a-bf0e617043ba.json`

<!-- run:94558768-8237-4660-812a-def4e15bdea4 -->
### Run `94558768-8237-4660-812a-def4e15bdea4` — 2026-11-02T14:15:44.863000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 5 / 0 / 0 / 0 (total 5)
- Pass rate (non-blocked): 100.0% (5/5 non-blocked)
- Configuration: `{'category': 'proactive_outbound', 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/94558768-8237-4660-812a-def4e15bdea4.json`

<!-- run:09e091e3-f31a-4b48-a8b0-4696a7a5cab4 -->
### Run `09e091e3-f31a-4b48-a8b0-4696a7a5cab4` — 2026-11-02T14:20:42.358000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 24 / 0 / 0 / 0 (total 24)
- Pass rate (non-blocked): 100.0% (24/24 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': True, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/09e091e3-f31a-4b48-a8b0-4696a7a5cab4.json`

<!-- run:acf8c8f2-9e30-4168-9e29-362829bf1052 -->
### Run `acf8c8f2-9e30-4168-9e29-362829bf1052` — 2026-11-03T08:28:22.028000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 11 / 10 / 0 (total 22)
- Pass rate (non-blocked): 8.33% (1/12 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/acf8c8f2-9e30-4168-9e29-362829bf1052.json`

<!-- run:247b47e5-7059-40e3-96d8-c52a57e72622 -->
### Run `247b47e5-7059-40e3-96d8-c52a57e72622` — 2026-11-03T08:29:36.202000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 3 / 18 / 0 (total 22)
- Pass rate (non-blocked): 25.0% (1/4 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/247b47e5-7059-40e3-96d8-c52a57e72622.json`

<!-- run:01f085af-0718-4ddc-bb12-c5ef089ecf1d -->
### Run `01f085af-0718-4ddc-bb12-c5ef089ecf1d` — 2026-11-03T08:30:41.276000 UTC

- Persona: qa-batch; environment: qa; model: gpt-4o-mini
- Passed / failed / blocked / skipped: 1 / 2 / 19 / 0 (total 22)
- Pass rate (non-blocked): 33.33% (1/3 non-blocked)
- Configuration: `{'category': None, 'test_key': None, 'failed_from': None, 'dry_run': False, 'live_llm': False, 'trials': 1, 'filtered': True}`
- Report: `qa_reports/01f085af-0718-4ddc-bb12-c5ef089ecf1d.json`
