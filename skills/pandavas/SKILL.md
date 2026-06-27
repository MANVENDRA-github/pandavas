---
name: pandavas
description: Use when you want an autonomous, test-gated fix or small feature on a local repo - a five-agent loop (research, worker, test, judge, orchestrate) where deterministic Python verbs rule on whether the code is correct. Requires a repo whose test suite already runs locally.
---

# Pandavas

## Overview

pandavas resolves ONE coding task - a bug fix or a small, testable feature - on a repo you already have locally. You (the host model) play the LLM agents: Nakula (research), Arjuna (worker), Sahadeva (judge). Deterministic `python -m pandavas` verbs play Bhima (the test runner) and Yudhishthira (the loop controller). You propose; the verbs dispose.

**Core principle:** A model never decides whether the code is correct. `run-tests` and `decide` decide, by process exit code. Tests are ground truth; research hands over checked pointers, not prose.

## The Iron Law

```
THE PYTHON VERBS RULE.
No "it passes" without `run-tests` exit 0.   No "converged" without `decide` exit 0.
No delivery without `decide` exit 0 AND the human's approval.
```

## Procedure

Run every verb from the repo root with `--repo .`. Each prints one JSON line and sets a process exit code - **branch on the exit code (`$?`), not on your own judgement.** (`python -m pandavas` requires the engine installed: `pip install -e .` or `pip install pandavas`.)

0. **Parse** `$ARGUMENTS` into a repo path (default `.`) and the task text.

1. **Baseline.** `python -m pandavas baseline --repo . --task "<task>"`
   - Add `--test-command "<cmd>"` if detection is wrong, `--junit-xml <path>` for per-test rigor on non-pytest frameworks.
   - Read `baseline_failures`: these pre-existing failures are **tolerated** - do not try to fix them.
   - A clean error here means no test command could be found; pass `--test-command`.

2. **Research ONCE (Nakula).** Explore with Read/Grep/Glob. Derive concrete, testable `acceptance_criteria` and anchors (real repo-relative paths + 1-indexed line ranges you actually read). Write `.pandavas/brief.json` (schema below), then `python -m pandavas resolve-brief --repo .`
   - Exit 1: read `failures`, fix the anchors, rewrite, retry a few times.
   - Cannot anchor your claims to real lines? **STOP and say so** - never guess.
   - The brief is cached; do NOT re-research on later iterations.

   ```json
   {"task":"...","acceptance_criteria":["..."],
    "relevant_code":[{"path":"f.py","line_start":1,"line_end":9,"snippet":"...","why":"..."}],
    "conventions":[],"integration_points":[],"constraints":[],"open_questions":[],"confidence":{}}
   ```

3. **Iterate** - worker -> test -> judge -> decide:
   a. **Worker (Arjuna).** Re-read the REAL code at the anchors (snippets only orient). Make the change with Edit/Write. If it is a bug with no test covering it, ADD a reproduction test as part of the change (fails before, passes after). On a retry, address the previous `decide` feedback.
   b. **Test (Bhima).** `python -m pandavas run-tests --repo .` - exit 0 = no new failures vs baseline; exit 1 = you introduced a failure or regression. Fix it; do NOT proceed on exit 1.
   c. **Diff.** `python -m pandavas diff --repo .` (renders `.pandavas/diffs/cumulative.diff` for review).
   d. **Judge-gate.** `python -m pandavas judge-gate --repo .` - exit 30 = auto-reject (failing tests or no change): skip the LLM judge, go to (f) with `--approved false` and the printed `feedback`. Exit 0 = go to (e).
   e. **Judge (Sahadeva, fresh context).** Spawn the **pandavas-judge** subagent (Task tool) with ONLY: the `acceptance_criteria`, the cumulative diff, and any task-relevant tests still failing; it returns `{"approved": bool, "feedback": str}`. If your harness has no subagent primitive (e.g. Cursor), instead do one clean review pass as an independent reviewer who did NOT write the change, weighing only the diff + criteria + test state. Prefer the subagent when available - it is genuinely independent; the fallback is weaker.
   f. **Decide (Yudhishthira).** `python -m pandavas decide --repo . --approved <true|false> --feedback "<judge feedback>"` - branch on exit code:
      - **0** -> converged. Go to 4.
      - **10** -> continue. Read `feedback`, loop to (a).
      - **20** -> stopped (`did_not_converge`); `decide` has already restored the best attempt to disk. Go to 5.

4. **Deliver (converged).** Show the cumulative diff and the red->green tests (`newly_passing`). Then ask the human before committing: `python -m pandavas commit --repo . --task "<task>"` (or `--branch <name>`). **Never commit without approval.**

5. **Honest failure (did_not_converge).** Report the `termination_reason` (`cap` / `oscillation`), the best attempt now on disk, and which task-relevant tests still fail. Never dress a failing result as a pass.

## Output

```
### Task
<task> on <repo>

### Loop
baseline failures (tolerated): <...>
iterations: <n>   status: converged | did_not_converge (<reason>)

### Change
<cumulative diff, or branch name + files changed>
red->green: <newly_passing tests>

### Proof (deterministic verdicts - the "verified" column)
$ python -m pandavas run-tests --repo .   -> exit 0
$ python -m pandavas decide ... --approved true   -> status converged (exit 0)

### Not verified
<gaps, untested paths>
```

Close with the **agent-suggested vs. deterministically-verified** split: the LLM steps (research, the edit, the judge's reasoning) are *suggested*; the verb exit codes (`resolve-brief`, `run-tests`, `decide`) are *verified*. If a claim has no exit code behind it, label it unverified.
