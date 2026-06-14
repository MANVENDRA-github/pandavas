# pandavas

**An autonomous multi-agent system that resolves a coding task — a bug fix or a
feature — on a repository you already have locally.** Point it at a repo, describe
the task, walk away. It researches the code, writes the change, verifies it
against tests, has an independent agent judge it, and loops until the change
passes or it honestly reports that it could not.

> **Status:** P0 / v0 in progress — see [`docs/SPEC.md`](docs/SPEC.md) for the
> full design and phase plan. The planning scaffold is in place; the code is being
> built skeleton-first (executor + orchestrator loop before individual agents).

---

## The five agents

Five agents, mapped to the five Pandava brothers by each one's strongest trait.
The hierarchy is built in: the orchestrator is the eldest brother the others obey.

| Role             | Brother      | Does                                                                |
|------------------|--------------|--------------------------------------------------------------------|
| Orchestrator     | Yudhishthira | Coordinates everyone, owns state, runs the loop, decides done/retry. |
| Research         | Nakula       | Explores the repo, returns an *anchored brief* — pointers, not prose. |
| Worker / Draft   | Arjuna       | Reads the real code at the anchors, writes the change (and the test). |
| Test (execution) | Bhima        | Runs the test suite. **Deterministic — not an LLM.** The ground truth. |
| Judge / QA       | Sahadeva     | Fresh-context review of the diff + tests against the spec. Verdict on demand. |

---

## How it works

1. **You** point pandavas at a local repo, describe the task, optionally set a
   test command, and run it.
2. **Nakula (Research)** finds the relevant code and returns an anchored brief:
   file + line ranges + snippets + acceptance criteria + conventions + pitfalls.
   Every anchor is checked to resolve to real lines before anything proceeds.
3. **Arjuna (Worker)** re-reads the real code at those anchors. For a bug with no
   covering test, it first writes a **failing test that reproduces the bug**, then
   fixes until that test goes **red → green**.
4. **Bhima (Test)** runs the suite, confirms red → green and no regressions, and
   reports objective pass/fail.
5. **Sahadeva (Judge)** reviews the diff and test results against the acceptance
   criteria with fresh context, checks the generated test isn't vacuous, and
   approves or rejects with specific feedback.
6. **Yudhishthira (Orchestrator)** decides: done, or retry with the judge's
   feedback — converging on tests as the objective signal, with oscillation
   detection and a hard cap.

**You get back:** a branch/diff with the change, a new regression test, and a full
run trace. If it can't converge, you get the best attempt — labeled honestly —
with the remaining failures surfaced.

---

## Quick start

> TODO — populated once P0 code lands. Anticipated shape:

```bash
# 1. Clone and install
git clone https://github.com/<you>/pandavas.git
cd pandavas
pip install -r requirements.txt

# 2. Add your own API keys
cp .env.example .env
#   then edit .env with your keys

# 3. Run a task against a local repo
python -m pandavas run \
  --repo /path/to/your/local/repo \
  --task "Bug: app crashes on empty form submit; should show a validation error" \
  --test-command "pytest"     # optional; auto-detected if omitted
```

---

## Configuration

- pandavas uses **your own** API keys — copy `.env.example` to `.env` and fill in
  your keys. The real `.env` is gitignored and is never committed.
- Runs on **free inference tiers** by design (zero-budget). Model and provider are
  configurable.

---

## Project structure

```
pandavas/
├── README.md                   this file
├── CLAUDE.md                   operating rulebook (scope lock + house rules)
├── .env.example                copy to .env and add your keys
├── .gitignore
├── docs/
│   ├── SPEC.md                 source of truth — full design + phase plan
│   └── HANDOVER.template.md    long-session baton (copy → fill → delete)
└── src/                        TODO — P0 code (executor + orchestrator loop)
```

---

## Scope & non-goals

pandavas works on a repo you **already have running locally** — it does not
reconstruct arbitrary environments from scratch. It is **not** a deterministic
compiler (output varies run to run; only the test+judge gate is the contract),
**not** a general CI service, and it does **not** guarantee a fix exists for every
task — it reports honest failure rather than faking success. Full list in
[`docs/SPEC.md`](docs/SPEC.md) §11.

---

## License

TODO — choose a license before making the repo public (MIT is the common default
for clone-and-use OSS tooling).
