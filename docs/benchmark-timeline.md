# Reading Merani benchmark time

`merani analytics` summarizes code-review runs from `review-runs`; `plan status`
reports planning state and the next action. Neither joins one planning lineage to
one code-review lineage or measures a controller's whole task. The read-only
`merani_timeline.py` export joins their persisted attempt receipts and point
timestamps without opening reviewer packets or writing to either store:

```bash
python3 skills/merani/scripts/merani_timeline.py \
  --plan-dir "$HOME/.codex/merani-plans/<session-id>" \
  --review-dir "$HOME/.codex/review-runs/<workflow-directory>" \
  --start 2026-09-14T11:24:00.277Z \
  --finish 2026-09-14T12:45:22.370Z
```

The output contains no repository roots, private store paths, prompts, reports,
source, or token-bearing diagnostics. It counts a repeated attempt ID once and
rejects conflicting duplicates or mixed workflow identities unless every
included workflow is explicitly selected with repeated `--review-workflow`
flags. Selectors must resolve in the chosen review directory; unselected
workflows are excluded. `not_started`
reservations are not provider attempts. A launched, interrupted, or resumed
attempt with unknown duration or cost stays unknown; a recovery timestamp is
not treated as the subprocess end. `known_provider_duration_seconds` sums known
attempt durations; `provider_occupied_seconds` unions their valid time intervals
so parallel attempts cannot inflate elapsed time. Only when every counted
attempt has a complete interval inside the supplied benchmark clock does
`non_provider_or_unobserved_seconds` appear. That remainder includes local CLI,
controller tools, model activity, pauses, and anything not instrumented. It is
not a Merani overhead or idle-time measurement. The export cannot recover a
full CLI-local duration from point timestamps; instrument the controller's CLI
invocation boundaries separately if that number is needed.

## Historical 2026-09-14 observations

Times below are UTC and from the immutable receipt and controller records in
the two benchmark lineages. They describe these runs, not a controlled speed
comparison. The HTTP lanes started 0.15 seconds apart and ran concurrently.
The JSON Patch lanes also overlapped. The benchmark's manually entered HTTP
`external_reviewer_attempts=0` is wrong; it does not indicate missing receipts.

| HTTP framing milestone | Recorded time |
| --- | --- |
| Benchmark start; planning session created | 11:24:00.277; 11:26:35.534 |
| Context; external evidence captured | 11:27:02.953; 11:27:48.260 |
| Evidence critique provider; decision | 11:28:07.612–11:29:26.160; 11:30:10 |
| First draft; plan critique 1; revised draft | 12:21:54; 12:23:09.738–12:24:33.390; 12:25:46 |
| Plan critique 2; final publication | 12:26:12.516–12:28:08.538; 12:29:31.751 |
| Implementation tests; repair review | 12:33:40 onward; 12:36:21.511–12:39:07.285 |
| Confirmation; final gate; source verify | 12:40:09.117–12:42:27.014; 12:43:29.613; 12:44:44.162 |
| Commit; benchmark finish | 12:43:55; 12:45:22.370 |

The HTTP five completed Claude receipts total **581.989 s** and **$1.23839**
of reported API-price equivalent. Their occupied wall intervals total
**581.892 s**. The benchmark records **4,882.092 s** elapsed; its printed
millisecond timestamps differ by **4,882.093 s**, a 1 ms rounding discrepancy.
Using those printed timestamps, **4,300.201 s** is outside the five provider
intervals. A controller transcript has a tool result at 11:30:25.687 and no
further tool call until 12:21:54.442, a **51m 28.755s** uninstrumented gap.
The transcript has a token-count event at 12:21:16 but no activity interval
that attributes the gap. It cannot be called provider execution, Merani local
work, controller thinking, a tool wait, or idle time from these records.

| JSON Patch milestone | Recorded time |
| --- | --- |
| Benchmark start; planning session created | 10:33:54; 10:35:52.530 |
| Initial draft; plan critiques; revised draft | 10:37:42.200; 10:38:09.460–10:39:49.086 and 10:40:52.712–10:42:23.745; 10:40:34.706 |
| Plan publication; implementation tests | 10:43:31.448; by 10:46:48 |
| Repair reviews | 10:48:41.432–10:51:50.326; 10:53:13.274–10:55:31.433 |
| Confirmation; gate; source verify | 10:56:05.830–10:57:57.657; 10:58:41.643; 10:59:38.983 |
| Commit; benchmark finish | 10:58:53; 11:00:53 |

The JSON Patch five completed Claude receipts total **629.631 s** and
**$1.0794534** API-price equivalent; their occupied intervals total
**629.538 s**. The benchmark records **1,619.501 s**. Its printed start and
finish timestamps have only whole-second precision and span 1,619 seconds.
Using the benchmark elapsed value, **989.870 s** is outside the summed provider
durations; using the printed timestamp interval and occupied union, the export
shows **989.462 s** outside provider intervals. Neither figure identifies its
component activities.

For an additional, non-additive controller view, pairing each main-session tool
call with its output and subtracting provider intervals leaves **168.897 s**
(HTTP) and **142.284 s** (JSON Patch) in tool spans whose input contained a
Merani CLI command, plus **22.929 s** and **9.720 s** in other tool spans.
These are tool-call envelopes, including shell startup and possible bundled
commands, not exact CLI-local execution. With this disjoint tool-span method,
**4,108.375 s** (HTTP) and **837.458 s** (JSON Patch) have no paired tool or
provider interval in the primary controller trace. The JSON Patch trace uses
the whole-second benchmark clock; these numbers inherit its precision limit.
Tool and provider intervals must not be added without removing overlap.

The repeated planning and code-review critiques and mandatory confirmation are
expected workflow policy costs. The receipt totals show real provider time, but
the long HTTP planning interval is dominated by missing interval observability
between evidence critique and the first draft. There is no demonstrated Merani
processing slowdown to optimize from these sessions. A lower end-to-end elapsed
time in a future run would require controlled, non-concurrent repetitions with
controller gaps bounded; this export itself does not make reviews faster.

## Later HTTP framing session, 2026-09-14

The later `http_framing_benchmark_awake` Merani lane ran from 13:34:53.638 to
14:27:53.908 UTC (**3,180.271 s** by its benchmark clock). Four planning
critiques consumed **454.280 s** of recorded Claude subprocess time. Five
code-review attempts across two successive workflows consumed **1,172.611 s**;
the nine receipts total **1,626.891 s**. Their occupied timestamp intervals
total **1,626.693 s**. The primary controller trace has **234.065 s** in paired
tool spans containing Merani CLI commands outside those provider intervals,
**30.413 s** in other paired tool spans, and **1,289.099 s** without a paired
tool or provider interval. Tool spans include process setup and possibly
several commands; they are not exact local CLI time. There is no matching plain
lane in this benchmark directory or controlled before/after speed measurement.

The four plan critiques raised different concrete issues, including a broken
shell verification command. The first code-review confirmation found an O(n²)
per-byte parser scan and a missing incremental-feed test. A source fix required
a successor workflow; its first repair review found an additional atomicity
test gap, followed by repair and fresh confirmation. These rounds supplied
observable value. Dropping critiques, the successor, or confirmation would
weaken the evidence for this session.

The controller also submitted several ready claim assurances through repeated
single-claim `assure` invocations. Both `assure` and `assure-batch` call the same
transaction validator and freshness check. In isolated temporary repositories
with a fake provider and four claims, three alternating measurements gave
**1.290–1.303 s** for four single CLI calls and **0.322–0.326 s** for one batch
call. The final assurance documents matched after timestamp fields were
removed. Batching ready decisions on one run therefore removes redundant CLI
and validation work without reducing reviewer rounds or changing the gate.
The measured local saving is about one second per four-claim group; the larger
controller tool-call envelopes cannot be assigned to CLI execution alone.

This session has two successor workflow IDs under one review directory. To
reproduce the combined receipt summary, pass both exact IDs:

```bash
python3 skills/merani/scripts/merani_timeline.py \
  --plan-dir "$HOME/.codex/merani-plans/<planning-id>" \
  --review-dir "$HOME/.codex/review-runs/<review-directory>" \
  --review-workflow "<first-workflow-id>" \
  --review-workflow "<successor-workflow-id>" \
  --start 2026-09-14T13:34:53.638Z \
  --finish 2026-09-14T14:27:53.908Z
```
