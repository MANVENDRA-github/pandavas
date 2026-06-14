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

- **Work is limited to P0 / v0 only** (see `docs/SPEC.md` §10).
- **Do not implement P1, P2, or P3 features** unless the user explicitly says
  "lift the scope lock."
- P0 deliverable, and nothing beyond it:
  - A deterministic **executor**: detect + run the local test command, capture
    red/green.
  - A **LangGraph orchestrator loop** wired to **stub agents** (the agents return
    placeholder output for now — real agent logic is P1+).
  - **One trivial bug fixed end-to-end** on one local repo, manual invocation.
- If a task seems to require P1+ work, **stop and ask** — do not quietly expand
  scope.

## Build order (non-negotiable)

> Skeleton first, muscle later.

1. Executor (test-command detection + run + red/green capture).
2. Orchestrator loop (LangGraph) wired to stub agents.
3. One trivial task end-to-end (research → worker → test → judge, all stubbed
   except the executor).
4. **Only then** flesh out individual agents — and only when the scope lock is
   lifted.

Do not start by polishing agent prompts. The riskiest piece is execution; prove
it first.

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
