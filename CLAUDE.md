# CLAUDE.md — pandavas

> This file is auto-read by Claude Code at the start of every session. It is the
> operating rulebook. The full design lives in [`docs/SPEC.md`](docs/SPEC.md) —
> that file is the source of truth; this file governs *how you work* in the repo.

---

## Project

**pandavas** is a multi-agent system that autonomously resolves a single coding
task (bug fix or feature) on a repository the user already has locally. Research →
Worker → Test → Judge, coordinated by an Orchestrator, looping until the change
passes the gate (tests pass **and** judge approves) or it honestly reports it
could not. Full design: `docs/SPEC.md`.

## Agent → Brother map

| Role             | Brother      |
|------------------|--------------|
| Orchestrator     | Yudhishthira |
| Research         | Nakula       |
| Worker / Draft   | Arjuna       |
| Test (execution) | Bhima        |
| Judge / QA       | Sahadeva     |

The test runner (Bhima) is **deterministic — not an LLM.** Do not implement it as
an agent.

---

## SCOPE LOCK — read before writing anything

- **P0 / v0 is COMPLETE** (see `docs/SPEC.md` §10): deterministic executor,
  LangGraph orchestrator loop wired to stub agents, CLI, and one trivial bug
  fixed end-to-end on a local repo.
- **P1 is COMPLETE:** real **Nakula** (research + anchored typed brief +
  deterministic resolve gate), real **Arjuna** (worker + path-safe edits), and a
  real verification loop end-to-end. The **Judge (Sahadeva) is still a stub.**
- **P2 is COMPLETE:** real **Sahadeva** judge (diff + results vs
  acceptance_criteria, adequacy check, anchored feedback), **regression-aware
  Bhima** (baseline run, pytest-first JUnit XML, exit-code fallback),
  **oscillation detection**, and **best-attempt restore** at the cap.
- **P3 is COMPLETE** (scope lock lifted by explicit instruction):
  - **CLI/UX**: run report, offline wiring check, JSON report + per-iteration
    trace, clean error handling, token-usage reporting.
  - **Client docs**: README + LICENSE.
  - **Git delivery**: a converged change is committed to a new branch.
  - **Per-test rigor for any framework** via `--junit-xml` (universal JUnit XML);
    pytest auto-captured.
  - **Red→green surfacing** (`newly_passing`), **restore deletion-handling**
    (strays removed on restore), **LLM retry/backoff**, **CI** (GitHub Actions).
- **P4 is COMPLETE** (keyless skill mode): the deterministic core is exposed as CLI
  verbs (`src/pandavas/spine.py`) and a `/pandavas` command + skill ships for Claude
  Code and Cursor, so the system runs with no API key on the host harness's model.
  Strictly additive; the `run` path is unchanged. See `docs/SKILL_MODE.md` and
  `docs/SPEC.md` §12.
- **Quality posture:** keep the suite green (`python -m pytest`), keep CLI stdout
  ASCII-only (Windows-first), no hardcoded paths, real `.env` never committed.

## Possible future work (ask before starting)

- Deeper reproducibility hardening (persisted run manifests, seed pinning).
- Pre-fix RED isolation (run a new repro test against original code to prove it
  was genuinely red before the fix, beyond the baseline-vs-final signal).
- Multi-repo / batch runs; richer cost controls.

Do not start by polishing agent prompts. Prove each piece end-to-end before
moving to the next.

---

## House rules

- **No hardcoded machine paths.** No `D:\...`, no `C:\Users\...`. Use relative
  paths and config. This repo is public and others will clone it.
- **Secrets:** never commit a real `.env`. `.env.example` is the only env file in
  the repo; the real `.env` is gitignored.
- **No invention.** If a design point isn't in `docs/SPEC.md`, it isn't decided —
  ask, or mark `TODO`. Do not fill gaps with guesses.
- **Tests are ground truth.** Don't replace test execution with an LLM judgment.
- **Pin model strings** (never `"latest"`) and keep temperature ~0 for the
  agents, per `docs/SPEC.md` §8.
- **Honest failure over fake success.** If the loop can't converge, report it;
  never dress a failing result as a pass.

## Documents

- `docs/SPEC.md` — source of truth (design).
- `README.md` — public/client-facing overview.
- `docs/HANDOVER.template.md` — copy to `HANDOVER.md` during a long session,
  fill it, and **delete it** after the next session reads it.
- `MEMORY.md` — **auto-managed by Claude Code.** Do not hand-create it.
- `soul.md`, `.claude/hooks/` — added manually by the user later. **Do not create
  them.**

---

## Learned Rules

> Accumulate project-specific conventions here as they're discovered.

- **Skill mode is additive (keyless `/pandavas`).** The host harness's model
  (Claude Code / Cursor) plays the LLM agents while deterministic CLI verbs in
  `src/pandavas/spine.py` (`baseline`, `resolve-brief`, `run-tests`, `judge-gate`,
  `decide`, `restore`, `commit`, ...) own every gate. The verbs reuse `run`'s logic
  (`nodes.make_bhima_test` / `_better` / `_restore_snapshot`) and pass state through a
  gitignored `.pandavas/` dir; `decide` is the sole writer of `loop.json`. The
  standalone `python -m pandavas run` path and the six deterministic modules are
  unchanged. Packaging (`commands/`, `skills/`, `agents/`, `scripts/install-*`) is
  top-level and excluded from the wheel (pyproject packages `src/` only). Keep verb
  stdout ASCII-only (`json.dumps(..., ensure_ascii=True)`). Design: `docs/SKILL_MODE.md`.
