# pandavas — Design Spec

> Source of truth for the project. Every other document (CLAUDE.md, README.md)
> references this file. If a decision isn't written here, it isn't decided —
> mark it `TODO` rather than inventing it.

---

## 1. Overview

**pandavas** is a multi-agent system that autonomously resolves a single coding
task — a bug fix or a feature — on a repository the user **already has locally**.

The user points it at a local repo path, writes a task description, optionally
sets a test command, runs it, and walks away. The system researches the code,
writes a change, verifies it against tests, has an independent agent judge it,
and loops until the change passes or it honestly reports that it could not.

The name maps the five agents to the five Pandava brothers (see §3). The hierarchy
is encoded for free: the orchestrator is the eldest brother the others obey.

**What pandavas is not** — see §11 Non-Goals. Read that section before assuming a
capability.

---

## 2. User Flow

**Input**

- `repo_path` — path to a local repository the user already has working.
- `task` — a natural-language description of the bug or feature.
- `test_command` *(optional)* — override for the command used to run tests; if
  omitted, the system auto-detects it (see §5).

**Process** — Orchestrator drives the loop: Research → Worker → Test → Judge →
(retry or done). Detailed in §3–§7.

**Output**

- A branch / diff containing the change.
- A new regression test the repo did not have before (for bug fixes).
- A full run trace: research brief → diffs → test results → judge verdicts, per
  iteration.
- **If it could not converge:** the best attempt produced, clearly labeled
  `did not converge`, with the remaining failures surfaced for the user to
  finish. It is never presented as success.

---

## 3. Agents

Five LLM agents plus one **deterministic** component (the test runner is not an
LLM), mapped to the Pandava brothers by each brother's single strongest trait.

| Agent role        | Brother       | Why this brother                                                                 |
|-------------------|---------------|----------------------------------------------------------------------------------|
| Orchestrator      | Yudhishthira  | The eldest, the king the others obey; the dharma-bound decision-maker.            |
| Research          | Nakula        | In the Rajasuya he scouted and conquered the western lands — goes out, returns territory. |
| Worker / Draft    | Arjuna        | The peerless one who executes the central craft with total focus ("only the bird's eye"). |
| Test (execution)  | Bhima         | Raw force applied until things break — adversarial verification; the all-brawn, no-LLM component. |
| Judge / QA        | Sahadeva      | The wisest, knows all, but speaks his judgment **only when asked** — a verdict on invocation. |

### 3.1 Yudhishthira — Orchestrator

- Coordinates all agents and owns the **shared state**.
- Controls the loop: decides done / retry / rollback.
- Detects **oscillation** (see §7) and breaks early.
- Enforces a **hard iteration cap**.
- Implemented as a **LangGraph state machine — not a reasoning agent.** It is
  control flow plus state, not an LLM making freeform decisions.

### 3.2 Nakula — Research

- Explores the repo and (where needed) external sources.
- Emits the **anchored brief** defined in §4 — pointers and evidence, **not prose
  conclusions**.
- Its job is to produce an *index into the real code*, not a *narrative about it*.

### 3.3 Arjuna — Worker / Draft

- Re-reads the **real code** at the brief's anchors (does not trust the brief's
  prose; see §4 Worker Protocol).
- For a bug with no covering test: **first writes a failing reproduction test**,
  then implements the fix (see §6).
- Writes the change, staying scoped to `acceptance_criteria`.

### 3.4 Bhima — Test (execution)

- **Deterministic. Not an LLM.**
- Runs the test command (auto-detected or overridden) in the repo's existing
  local environment.
- Captures exit code and logs; reports pass/fail and any regressions.
- This is the system's **ground truth**. Ground truth is code, not a model.

### 3.5 Sahadeva — Judge / QA

- Runs with **fresh context** (did not write the code).
- Reviews the diff + test results against `acceptance_criteria`.
- Validates that any agent-written test is **non-vacuous** (anti-gaming; see §6).
- Returns **approve** OR **reject with structured, actionable feedback** tied to
  specific anchors.

---

## 4. Research Brief Contract (Nakula → Arjuna)

The brief is a **typed artifact** held in orchestrator shared state and passed
**by reference**, not inlined into the worker's prompt. This keeps the worker's
context lean and forces grounding.

### 4.1 Schema (conceptual)

```
Anchor:
  path:        str         # file path relative to repo root
  line_start:  int
  line_end:    int
  snippet:     str         # short, for orientation only — NOT a substitute for reading
  why:         str         # one line: why this location matters

ResearchBrief:
  task:                str
  acceptance_criteria: list[str]    # shared with the Judge — the shared definition of "done"
  relevant_code:       list[Anchor] # where the work happens
  conventions:         list[Anchor] # how this repo does things (test fw, error style, naming)
  integration_points:  list[Anchor] # where new code plugs in
  constraints:         list[str]    # don't-touch / deprecated / external quirks
  open_questions:      list[str]    # low-confidence items to verify before trusting
  confidence:          dict[str, float]   # optional, per-claim
```

### 4.2 Worker Protocol (how Arjuna consumes the brief)

1. **Anchors are truth; prose claims are advisory.** Before depending on any
   claim, open the anchor with the worker's own read tool and confirm against
   live code. Snippets orient; they do not replace reading.
2. **Verify `open_questions` first.** Spend verification effort where Research
   flagged low confidence; trust high-confidence anchors lightly.
3. **Build against `acceptance_criteria`, not the prose.** The same list goes to
   the Judge, so worker and judge cannot drift onto different specs.

### 4.3 Resolve Gate (deterministic, before Worker runs)

The orchestrator validates the brief before handing it to the worker:

- Brief is schema-valid, **and**
- **Every anchor resolves** to a real file with those exact lines existing.

A dangling anchor means Research hallucinated → loop back to Nakula. No LLM is
needed for this check, and it kills the single biggest failure mode (the worker
building on a stale or invented summary).

---

## 5. Execution Model

- Tests run in the repo's **existing local environment** — pandavas does not
  reconstruct arbitrary environments from scratch. The user already has the repo
  working; pandavas leans on that.
- **Test-command discovery:** auto-detect from manifests
  (`package.json`, `pyproject.toml`, `requirements.txt`, `go.mod`, `Cargo.toml`,
  `pom.xml`, …), with a user `test_command` override that always wins.
- **Sandbox is optional** — it is the user's own machine and their own repo, so
  the safety bar is lower than running a stranger's code. Optional hardening, not
  a blocker.
- **Executor behind an interface.** The execution backend (local subprocess) sits
  behind an interface so it can later swap to a hosted sandbox (e.g. E2B-style)
  without touching any agent logic.

---

## 6. No-Tests Fallback

When the gate (tests) doesn't exist yet, the system **manufactures** it. This
*raises* quality — it leaves the repo with a regression test it lacked.

- **Bug fix:** Worker writes a test that reproduces the bug, then proves it is
  real by running it on the **unfixed** code and confirming it **fails (RED)**.
  Then fixes until it **passes (GREEN)**. A reproduction test that was never RED
  proves nothing — this check is mandatory.
- **Feature:** Worker derives acceptance tests from `acceptance_criteria`, writes
  them, and implements to **GREEN**.
- **Anti-gaming:** because the system writes its own tests, the **Judge**
  (fresh context) reviews the generated tests for *adequacy* — do they actually
  encode the requirement, or are they vacuously passing? — not just the code.

The **RED → GREEN** transition is the objective proof of both a real test and a
working change.

---

## 7. Convergence Loop

- **Objective progress signal:** tests. `N` failing → `N−1` failing is measurable
  convergence the LLM judge alone cannot provide.
- **Regression guard:** a previously-passing test that now fails is rejected
  immediately.
- **Judge feedback must be specific and actionable** — failing criteria tied to
  anchors, never "improve this." Vague feedback is what causes oscillation;
  concrete cumulative feedback is what stops it.
- **Oscillation detection:** if the same test fails twice after a "fix," or the
  diff churns the same lines, break early — do not burn the whole budget.
- **Hard iteration cap.**
- **At the cap:** return the **best attempt** (most tests passing + highest judge
  score), labeled `did not converge`, with remaining failures surfaced. **Never
  present a failing result as success.**

The acceptance gate (tests pass **and** judge approves) never loosens — the cap
only changes how the not-converged case is *reported*.

---

## 8. Reproducibility

LLM generation is not deterministic. So the guarantee is moved from *generation*
to *acceptance* — the correct contract for an autonomous coding agent.

- **Pin the harness:** exact model string (never `"latest"`), temperature ~0,
  fixed prompts, pinned harness dependency versions. The harness is reproducible
  even when model output varies.
- **The promise:** "produces a change that passes the gate, or reports that it
  could not" — not byte-identical output. Tests are the reproducible contract.
- **Full traces:** every run logs brief → diffs → test results → judge verdicts,
  per iteration. When a re-run differs, it is debuggable, and a successful demo's
  trace is evidence the system works.

---

## 9. Stack & Constraints

- **Language:** Python.
- **Orchestration:** LangGraph (state machine for the loop + the judge gate).
- **Budget:** zero. Free inference tiers (e.g. Groq / Gemini free tiers);
  optional OpenRouter for model choice. The **client supplies their own API keys**
  via `.env`. Ship `.env.example` only; gitignore the real `.env`; **no hardcoded
  machine paths** (no `D:\...`, no `C:\Users\...`).
- **Dev environment:** Windows.
- **Delivery:** public repo; the client clones it and runs with their own keys.
- **Scope:** repositories the user already has locally.

---

## 10. Phase Plan

> **P0 is the ONLY currently in-scope phase.** Do not implement P1–P3 until the
> scope lock in `CLAUDE.md` is explicitly lifted.

- **P0 / v0 (IN SCOPE)** — Skeleton first, muscle later.
  - Deterministic **executor**: detect + run the local test command, capture
    red/green.
  - **LangGraph orchestrator loop** wired to **stub agents**.
  - Goal: **one trivial bug fixed end-to-end** on one local repo, manual
    invocation. This proves the wiring and surfaces real edge cases before any
    single agent is polished.
- **P1** — Real **Nakula** (anchored brief + resolve gate) and real **Arjuna**
  (read anchors, repro-test, fix).
- **P2** — Real **Bhima** integration (baseline, red→green, regression check),
  real **Sahadeva** (judge rubric, adequacy check, structured feedback), and the
  full convergence / oscillation / cap logic.
- **P3** — Reproducibility hardening, no-tests robustness, multi-language
  detection, CLI/UX, client setup docs.

---

## 11. Non-Goals

- **Not a deterministic compiler** — output varies run to run; only the gate is
  the contract.
- **Not a general CI service** — it runs locally, on demand.
- **Does not reconstruct arbitrary environments from scratch** — it relies on the
  repo working locally.
- **Does not guarantee a fix exists** for every task — it reports honest failure
  rather than faking success.
- **Not a multi-repo / org-wide tool** — one local repo per run.
