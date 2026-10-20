# Persona QA issues

This file is generated from an executed QA run. Counts below are from that run. Unexecuted tests are not treated as passed.

## Run Information

- **Run ID:** `75d3aa2a-0d8f-4c68-8d18-91779f15ba15`
- **Started:** 2026-10-20T07:48:02.637000 (UTC)
- **Completed:** 2026-10-20T10:06:34.254000 (UTC)
- **Timezone:** timestamps in this summary are UTC. Persona answers use the configured IANA zone (Europe/London for Sarah).
- **Environment:** qa
- **Tested persona:** qa-batch
- **Build:** dev
- **Model / provider:** gpt-4o-mini / openai
- **Prompt version:** not recorded
- **Live LLM judging:** False

## Execution Summary

- **Discovered / executed:** 153 / 153
- **Passed:** 109
- **Failed:** 2
- **Blocked:** 42
- **Skipped:** 0
- **Pass rate (executed, non-blocked):** 98.2% (109/111 non-blocked)
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

### ISS-90492ce4: PROACTIVE-009 failed

- **Severity:** High
- **Category:** proactive_engagement
- **Status:** Open
- **Classification:** probable product defect (unverified hypothesis, not confirmed)
- **Affected tests:** `PROACTIVE-009`
- **Preconditions:** isolated `qa-` persona and user; deterministic stub LLM unless the run set live judging.
- **Reproduction:**
  1. Seed the suite and run `python -m persona_runtime.qa run --test-key PROACTIVE-009` on mongomock or a database whose name contains `qa` or `test`.
  - User: set_proactive
  - User: schedule_resume
- **Expected:** Verify message frequency caps
- **Actual:** Proactive policy violation
- **Run reference:** see the run ID in Run Information. Detailed records: `qa_reports/<run_id>.json`.
- **Evidence:**
  - `proactive_permission_respected` fail: Proactive policy violation (expected={'expect_allow': False, 'reason_contains': 'max_per_day'}, actual={'allow_outbound': False, 'situation': 'user_unavailable', 'reason': 'persona_unavailable', 'use_engagement_in_reply': False})
- **Suspected root cause:** Hypothesis: Proactive policy gates misconfigured or not consulted.
- **Recommended fix:** Review evaluate_proactive_policy and resume scheduling.

### ISS-a09c73c9: PROACTIVE-011 failed

- **Severity:** High
- **Category:** proactive_engagement
- **Status:** Open
- **Classification:** probable product defect (unverified hypothesis, not confirmed)
- **Affected tests:** `PROACTIVE-011`
- **Preconditions:** isolated `qa-` persona and user; deterministic stub LLM unless the run set live judging.
- **Reproduction:**
  1. Seed the suite and run `python -m persona_runtime.qa run --test-key PROACTIVE-011` on mongomock or a database whose name contains `qa` or `test`.
  - User: set_proactive
  - User: schedule_resume
- **Expected:** Follow-up is not sent before its configured trigger
- **Actual:** Proactive policy violation
- **Run reference:** see the run ID in Run Information. Detailed records: `qa_reports/<run_id>.json`.
- **Evidence:**
  - `proactive_permission_respected` fail: Proactive policy violation (expected={'expect_allow': False, 'reason_contains': 'min_interval'}, actual={'allow_outbound': False, 'situation': 'user_unavailable', 'reason': 'persona_unavailable', 'use_engagement_in_reply': False})
- **Suspected root cause:** Hypothesis: Proactive policy gates misconfigured or not consulted.
- **Recommended fix:** Review evaluate_proactive_policy and resume scheduling.

## Memory and Consistency Findings

Ledger contradictions (confirmed by the consistency ledger, not by an LLM judge):

- `CONTEXT-010` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Manchester', 'source': 'response', 'timestamp': '2026-10-20T07:57:14.938290Z', 'confidence': 1.0, 'status': 'stated', 'conver… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-10-20T07:57:14.994202Z', 'confidence': 1.0, 'status': 'state…
- `CONTEXT-015` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-10-20T08:01:43.858788Z', 'confidence': 1.0, 'status': 'state… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Northbridge Financial Group', 'source': 'response', 'timestamp': '2026-10-20T08:01:43.916487Z', 'confidence': 1.0, 'status': …
- `CONTEXT-015` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Northbridge Financial Group', 'source': 'response', 'timestamp': '2026-10-20T08:01:43.916487Z', 'confidence': 1.0, 'status': … later={'subject': 'persona', 'attribute': 'fact', 'value': 'Manchester Finance Office, 18 Alderbrook Square, Manchester, UK', 'source': 'response', 'timestamp': '2026-10-20T08:01:43.972…
- `FLOW-001` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Manchester', 'source': 'response', 'timestamp': '2026-10-20T08:40:16.141377Z', 'confidence': 1.0, 'status': 'stated', 'conver… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-10-20T08:40:16.197454Z', 'confidence': 1.0, 'status': 'state…
- `FLOW-001` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-10-20T08:40:16.197454Z', 'confidence': 1.0, 'status': 'state… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Aries', 'source': 'response', 'timestamp': '2026-10-20T08:40:16.253898Z', 'confidence': 1.0, 'status': 'stated', 'conversatio…
- `FORMAT-002` persona.fact: earlier={'subject': 'persona', 'attribute': 'fact', 'value': 'Manchester', 'source': 'response', 'timestamp': '2026-10-20T09:42:24.921837Z', 'confidence': 1.0, 'status': 'stated', 'conver… later={'subject': 'persona', 'attribute': 'fact', 'value': 'Management Accountant', 'source': 'response', 'timestamp': '2026-10-20T09:42:24.983194Z', 'confidence': 1.0, 'status': 'state…

## Timeline Findings

No failing timeline, date/time, or event-status assertions were recorded in this run.

## Infrastructure/Test Problems

### ISS-LIVE-LLM: Live semantic checks were not executed

- **Severity:** Needs Review
- **Category:** evaluation
- **Status:** Blocked
- **Classification:** blocked live-LLM check, not a persona defect
- **Affected tests:** `CONTEXT-001`, `CONTEXT-002`, `CONTEXT-003`, `CONTEXT-004`, `CONTEXT-005`, `CONTEXT-006`, `CONTEXT-007`, `CONTEXT-008`, `CONTEXT-009`, `CONTEXT-011`, `CONTEXT-012`, `FLOW-002`, `FLOW-004`, `FLOW-005`, `FLOW-006`, `FLOW-009`, `FORMAT-004`, `FORMAT-005`, `FORMAT-006`, `HUMAN-001`, `HUMAN-002`, `HUMAN-003`, `HUMAN-004`, `HUMAN-005`, `HUMAN-006`, `HUMAN-007`, `HUMAN-008`, `HUMAN-009`, `HUMAN-010`, `HUMAN-011`, `HUMAN-012`, `HUMAN-013`, `HUMAN-014`, `HUMAN-015`, `HUMAN-016`, `HUMAN-017`, `HUMAN-018`, `MEM-011`, `PROACTIVE-004`, `PROACTIVE-005`, `PROACTIVE-006`, `PROFILE-009`
- **Preconditions:** `QA_LLM` is not `live` and the run did not pass `--live-llm`.
- **Expected:** tone and optional topic checks run only with a live judge.
- **Actual:** those assertions returned `blocked` (`Live LLM evaluation disabled`). Required deterministic checks on the same cases are reflected in the case status; a case listed here had no product-defect failure.
- **Suspected root cause:** Hypothesis: opt-in live judging was not enabled for this run.
- **Recommended fix:** Re-run the listed keys with `QA_LLM=live` when an OpenAI key is available. Do not treat this block as a pass.

## Fixed and Re-tested Issues

No previously failing tests were recorded as newly passing in this run.

## Remaining Risks and Next Actions

- 2 probable product defect(s) remain open. Highest severity: High.
- 42 case(s) are blocked on live LLM judging and must not be read as passes.
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
