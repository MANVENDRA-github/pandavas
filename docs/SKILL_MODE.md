# Skill mode (keyless `/pandavas`)

> Design source of truth is [`SPEC.md`](SPEC.md). This document describes the
> additive **skill mode** layered on top of it. The standalone
> `python -m pandavas run` path is unchanged.

## Why two modes

pandavas runs in two ways that share one deterministic core:

| | Standalone (`python -m pandavas run`) | Skill (`/pandavas`) |
|---|---|---|
| LLM agents | pandavas's own LLM client + API key | the **host harness's model** (Claude Code / Cursor) - **no API key** |
| Orchestration | LangGraph state machine, one process | the host model follows a protocol, calling verbs via the shell |
| Determinism | **hard** - the process forces every gate | **soft** - the model must call the verbs and obey their exit codes |
| Best for | a CI-able, reproducible proof of the system | a frictionless, keyless fix from inside your editor |

Both call the **same** deterministic code, so a fix delivered in skill mode is gated
by the same regression-aware test logic the standalone mode is CI-tested against.

## The split across the process boundary

A subprocess cannot borrow the harness's model, so skill mode does not run the agents
as a subprocess. Instead it splits the work:

- **The host model owns the LLM-shaped steps:** research (Nakula), writing the edit
  (Arjuna), judging (Sahadeva).
- **The deterministic decisions stay in pandavas's Python**, exposed as LLM-free CLI
  verbs the skill calls: the resolve gate, the regression-aware test verdict,
  oscillation detection, the iteration cap, best-attempt restore, git delivery.

The model is the hands and eyes; the verbs are the rules. The skill protocol lives in
[`../skills/pandavas/SKILL.md`](../skills/pandavas/SKILL.md).

## The verb surface

Every verb takes `--repo`, prints one ASCII JSON line, and sets a process exit code.
They are implemented in [`../src/pandavas/spine.py`](../src/pandavas/spine.py), reusing
the same functions as `run` (`executor`, `testresults`, `edits`, `diffing`, `gitutils`,
`brief`, plus `nodes.make_bhima_test` / `_better` / `_restore_snapshot`).

| Verb | Role | Exit codes |
|---|---|---|
| `baseline` | Bhima | run the suite once; capture baseline + snapshots; init run state | 0 / 1 no test cmd |
| `detect-test` | - | print the auto-detected test command | 0 / 1 none |
| `resolve-brief` | gate | every anchor must resolve to real files/lines | 0 resolved / 1 dangling |
| `run-tests` | Bhima | regression-aware verdict vs baseline | **0 iff no new failures** / 1 |
| `diff` | - | render the cumulative / per-iteration diff to a file | 0 |
| `judge-gate` | Sahadeva | deterministic pre-LLM reject (failing tests / empty diff) | 0 review / 30 reject |
| `decide` | Yudhishthira | trace, best-attempt, oscillation, cap, restore-on-stop | 0 converged / 10 continue / 20 stop |
| `restore` | - | restore the best or baseline snapshot | 0 / 1 |
| `commit` | - | deliver a converged change to a new branch | 0 / 1 |
| `apply-edits` | - | optional path-safe full-file writer | 0 / 1 rejected |

## The `.pandavas/` working directory

Because the verbs are stateless processes, run state persists in a `.pandavas/`
directory under the target repo:

```
.pandavas/
  baseline.json     test command, junit path, baseline per-test, exit code
  brief.json        the resolved ResearchBrief (research-once cache)
  loop.json         iteration / signatures / best-attempt / trace / status
  last_test.json    the latest regression verdict
  snapshots/        baseline.json, pre_iter.json, best.json
  diffs/            cumulative.diff, iter.diff
```

It is kept out of your repo three ways: `baseline` appends `.pandavas/` to
`<git-dir>/info/exclude` (so a `commit` never stages it), every snapshot drops
`.pandavas/` keys, and `.pandavas` is in `retrieval.IGNORE_DIRS`. `decide` is the sole
writer of `loop.json` and recomputes diffs/signatures from snapshots, so a fabricated
model diff cannot game the loop.

## Fresh-context judge, per harness

The judge (Sahadeva) must not review its own work. Behind the deterministic
`judge-gate`:

- **Claude Code** spawns the **`pandavas-judge` subagent**
  ([`../agents/pandavas-judge.md`](../agents/pandavas-judge.md)) with only the
  acceptance criteria, the cumulative diff, and the still-failing tests - genuine
  fresh context.
- **Cursor** has no equal subagent primitive, so the judge runs as a fresh-pass
  self-review in shared context. This is **honestly weaker** (the reviewer has seen
  the worker's reasoning). The deterministic gates are identical on both; only the
  LLM-review independence degrades. For strict isolation, use Claude Code or the
  standalone `run`.

## Honest limitation: soft vs hard determinism

In standalone `run`, the process calls Yudhishthira unconditionally - the gates cannot
be skipped. In skill mode the host model must *choose* to call `run-tests` /
`judge-gate` / `decide` and *obey* their exit codes. An over-eager model could skip a
gate and claim success. This is mitigated (the Iron Law, the mandatory procedure, a
proof step that pastes real exit codes, `commit` gated behind `decide` exit 0 plus
human approval, and `decide` recomputing from snapshots) but not eliminated.

**`python -m pandavas run` remains the hard-determinism proof; `/pandavas` is the
keyless ergonomic path.**

## Install & use

```bash
pip install -e .                 # the engine, so `python -m pandavas` works
bash scripts/install-claude.sh   # or scripts/install-claude.ps1   (Claude Code)
bash scripts/install-cursor.sh   # or scripts/install-cursor.ps1   (Cursor)
```

Then, in any repo whose test suite already runs:

```
/pandavas . Fix the off-by-one in paginate()
```
