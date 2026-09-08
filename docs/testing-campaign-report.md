# Testing sandbox and reflection campaign

Date: 2026-09-08

Baseline commit: `6c8a328883e96fd0e9aca38f94d9d2286a7756e4`

Host: macOS 26.6.2 arm64, Python 3.12.8

Seed: `20260908`

The final pre-commit source campaign passed all six quick scenarios in 11.221
seconds of measured scenario command time. It used only local fake-provider
executables and synthetic authentication. Provider credits and network-backed
reviewers were not used.

| Scenario | Result | Main observation |
| --- | --- | --- |
| clean-gate | passed | Repair and confirmation ran, declared oracle passed, final was verified, and reviewed bytes were commit-bound |
| logged-out | passed | Preflight blocked with zero provider invocations and produced incomplete advisory reflection |
| malformed-resume | passed | One malformed attempt was retained and only the eligible failed provider was retried |
| invalid-utf8 | passed | No false clean result; bounded diagnostic bytes remained available |
| seeded-defect | passed | Independent oracle observed 9 instead of 5 and the queued finding was explicitly accepted |
| multi-repository-incomplete | passed | One completed and one failed repository left the workflow not ready |

The finding ledger contains zero confirmed Merani defects, one intentional
synthetic application defect, and one expected protective block. The queued
finding matched the separate ground truth and oracle; this validates mechanics
and is not an AI-discovery result.

An advisory review after commit `a635f33` found one confirmed campaign-contract
defect: generated records omitted `commands` even though the versioned schema
required it. The retained pre-fix active-install records reproduce the omission.
The successor change persists bounded normalized command entries, validates
required record fields during every campaign, and adds regressions for schema
conformance and the no-independent-discovery ledger label. The same review found
launcher size visibility and ordinary artifact retention gaps; the architecture
checker now emits launcher size signals and the reflection documentation states
that no automatic retention policy exists.

The small matched stress workload used 107 fixture files, 11 workflow documents,
two zero-sleep fake provider runs, and five repetitions per query:

| Measurement | Baseline | Candidate |
| --- | ---: | ---: |
| End-to-end repair, confirmation, finalization | 2.514s | 2.491s |
| Workflow status p50 / p90 | 0.257s / 0.258s | 0.257s / 0.261s |
| Analytics p50 / p90 | 0.128s / 0.131s | 0.129s / 0.131s |
| Reflection regeneration p50 / p90 | unavailable | 0.136s / 0.138s |

The single lifecycle delta was -0.023s. Process and filesystem noise dominate a
sample this small, so it does not establish a regression or improvement.
Reflection regeneration was directly observed; provider time was not estimated
or subtracted because the fake providers had zero configured sleep.

The selected medium stress case also passed with 407 files, 41 workflow
documents, and 12 query repetitions. Baseline/candidate lifecycle times were
3.043s/2.982s; status p50 was 0.264s/0.267s; analytics p50 was
0.126s/0.128s; and candidate reflection regeneration was 0.137s p50 and
0.138s p90. These are likewise descriptive local measurements.

The final source machine records, bounded command streams, and private run
artifacts were retained outside Git under:

`/private/tmp/merani-testing-feedback-evidence-final-source-v2/campaign-20260908T194944Z-20260908-26336/`

The matched stress roots and performance report remain under
`/private/tmp/merani-testing-feedback-evidence-final/`.

The representative finalized-confirmation reflection recorded completed
execution, `PASS_CLEAN`, confirmed confirmation, and fresh verification as
separate outcomes. It cited the durable attempt, final, verification, and
metadata fields; labelled cost as provider-reported; and stated that it had no
gate authority. Live provider behavior, reviewer accuracy, CI, deployment, and
production behavior remain outside this offline evidence.
