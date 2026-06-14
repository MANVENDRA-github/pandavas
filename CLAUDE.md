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
- **Active phase: P2.** In scope, and nothing beyond it:
  - **Real Bhima rigor:** baseline test run, **red→green** confirmation for the
    reproduction test, and **regression detection** (a previously-passing test
    that now fails is rejected). Per-test result parsing is **pytest-first** (via
    JUnit XML); non-pytest commands fall back to **exit-code-only**.
    (Multi-framework per-test parsing stays P3.)
  - **Real Sahadeva judge:** replace the stub with an LLM that reviews the change
    diff + test results against `acceptance_criteria`, validates that any
    agent-written test is **non-vacuous** (adequacy / anti-gaming), and returns
    **approve** OR **reject with specific, actionable feedback tied to anchors**.
  - **Convergence control:** oscillation detection (the same test fails twice
    after a "fix," or the diff churns the same lines → break early) and
    **best-attempt tracking** so the cap returns the best result, labeled
    honestly.
- **P3 stays LOCKED:** reproducibility hardening, multi-framework / multi-language
  per-test parsing, CLI/UX polish, and client setup docs.
- **Do not implement P3 features** unless the user explicitly says "lift the
  scope lock." If a task seems to require P3 work, **stop and ask** — do not
  quietly expand scope.

## Build order (non-negotiable)

> Deterministic gate before the stochastic part. Prove before polish.

1. **Diff capture** — deterministically capture the change diff for the judge.
2. **Real Sahadeva judge** — diff + test results vs acceptance_criteria,
   adequacy check, approve / reject-with-anchored-feedback.
3. **Bhima per-test rigor** — baseline, red→green, regression detection
   (pytest-first via JUnit XML; exit-code-only fallback).
4. **Oscillation + best-attempt-at-cap** — break early on churn/repeats; return
   the best attempt, labeled honestly.

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

> Accumulate project-specific conventions here as they're discovered. Empty for now.

-
