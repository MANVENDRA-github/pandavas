---
description: Autonomously resolve one test-gated bug fix or small feature on a local repo - research, worker, test, judge, orchestrate, where deterministic Python verbs rule on correctness.
argument-hint: <repo path or "."> <bug to fix / feature to add>
allowed-tools: Bash, Read, Edit, Write, Grep, Glob, Task
---
Use the **pandavas** skill.

Task (repo + what to fix or build): $ARGUMENTS

Baseline the suite, research once into an anchored brief and resolve-gate it, then loop worker -> run-tests -> judge-gate -> fresh-context judge -> decide until the verbs converge (`decide` exit 0) or honestly report they could not. The Python verbs rule on correctness: never claim success without `run-tests` exit 0, never claim convergence without `decide` exit 0.

Close by showing the diff, the red->green tests, and the deterministic verdicts (real exit codes). STOP for my approval before committing.
