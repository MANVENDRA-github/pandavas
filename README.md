# pandavas

**An autonomous multi-agent system that resolves a coding task — a bug fix or a
feature — on a repository you already have locally.** Point it at a repo, describe
the task, walk away. It researches the code, writes the change, verifies it
against tests, has an independent agent judge it, and loops until the change
passes or it honestly reports that it could not.

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

1. **Research** explores the repo and returns an *anchored brief* — file + line
   ranges + snippets + acceptance criteria. Every anchor is checked to resolve to
   real lines (a resolve gate) before anything proceeds.
2. **Worker** re-reads the real code at those anchors and writes complete-file
   changes; for a bug with no covering test it adds a reproduction test first.
3. **Test run** is deterministic and **regression-aware**: it compares against a
   baseline run and only accepts a change that introduces **no new failures** (a
   previously-passing test that now fails is rejected).
4. **Judge** is an independent LLM that reviews the cumulative diff and the *true*
   test state against the acceptance criteria, and checks any generated test isn't
   vacuous — approving, or rejecting with specific feedback.
5. **Loop:** the orchestrator retries with the judge's feedback, with
   **oscillation detection** (it breaks early if it keeps repeating itself) and a
   **hard iteration cap**. At the cap it restores the **best attempt** seen and
   reports `did not converge` honestly.

---

## Install

Requires **Python 3.10+**.

```bash
git clone https://github.com/<you>/pandavas.git
cd pandavas
pip install -e .
```

`pip install -e .` installs the dependencies (`langgraph`, `openai`,
`python-dotenv`, `pydantic`) and makes the `pandavas` package importable and
runnable as `python -m pandavas`.

---

## Configuration

pandavas uses **your own** API keys. Copy the template and fill it in:

```bash
cp .env.example .env
```

Then edit `.env`:

- **`PANDAVAS_LLM_PROVIDER`** — which provider the LLM client uses. Valid values:
  `groq`, `openrouter`, `gemini`, `openai`.
- **The matching provider key** — set the one for your provider:
  `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, or `OPENAI_API_KEY`.
- **The three model env vars** — pin an exact model id for each agent:
  - `PANDAVAS_RESEARCH_MODEL`
  - `PANDAVAS_WORKER_MODEL`
  - `PANDAVAS_JUDGE_MODEL`

**Finding valid model ids.** Pin exact ids — never `"latest"`. Query your
provider's models endpoint to see what is currently available. For Groq:

```bash
curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"
```

Suggested starting points (verify they are current against the endpoint above
before relying on them):

- `PANDAVAS_RESEARCH_MODEL=openai/gpt-oss-20b`
- `PANDAVAS_WORKER_MODEL=openai/gpt-oss-120b`
- `PANDAVAS_JUDGE_MODEL=openai/gpt-oss-20b`

The real `.env` is gitignored and is **never committed** — only `.env.example`
lives in the repo.

---

## Usage

```bash
python -m pandavas run --repo <path> --task "<description>" [options]
```

Flags for the `run` subcommand:

| Flag               | Required | Description                                                            |
|--------------------|----------|------------------------------------------------------------------------|
| `--repo`           | yes      | Path to a local repository you already have working.                   |
| `--task`           | yes      | Natural-language description of the bug or feature.                    |
| `--test-command`   | no       | Override the auto-detected test command (e.g. `"pytest"`).             |
| `--max-iterations` | no       | Hard cap on retry iterations (default: `6`).                           |
| `--offline`        | no       | Use stub agents (no LLM, no API key) to verify the install/wiring. The real executor still runs the tests. |
| `--report`         | no       | Path to write a JSON run report (summary + token usage + trace).       |
| `--trace`          | no       | Path to write the full per-iteration JSON trace.                       |
| `--junit-xml`      | no       | Path to a JUnit XML file your test command emits — enables per-test rigor for non-pytest frameworks (jest-junit, gotestsum, etc.). Relative paths resolve under `--repo`. |
| `--branch`         | no       | Branch name to commit a converged change to (default: auto from task). |
| `--no-git`         | no       | Do not create a git branch/commit on a converged change.               |

**Exit codes:** `0` if the run converged, `1` otherwise.

**On a converged run** (real, non-`--offline`) in a git repo, pandavas commits the
change to a new branch (named from the task, or `--branch`) so you get a reviewable
branch/diff. Use `--no-git` to skip. The report also prints cumulative token usage
and, where applicable, the tests that went **red→green**.

**`--offline`** runs the loop with placeholder agents and no LLM calls, so it
needs no API key. Use it right after install to confirm everything is wired up —
the real test executor still runs against your repo.

```bash
python -m pandavas run --repo . --task "smoke test" --offline
```

Example report:

```
pandavas - run report
repo:    /path/to/your/repo
task:    Fix add() returning the wrong result
status:  converged
iterations: 2

change diff:
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
```

If it cannot converge, the report shows `status:  did_not_converge`, a `reason:`
(`cap` or `oscillation`), and the best attempt's iteration. Pass `--report
run.json` to also capture the full machine-readable trace.

---

## Limitations & non-goals

- **Output is non-deterministic.** The guarantee is *"produces a change that
  passes the gate, or reports that it could not"* — not byte-identical output run
  to run.
- **At the iteration cap it returns the best attempt**, restored on disk and
  labeled `did not converge`, with remaining failures surfaced. It never presents
  a failing result as success.
- **Per-test regression rigor is pytest-native**; other frameworks get it by
  emitting JUnit XML and pointing pandavas at it with `--junit-xml`. Without
  parseable per-test results it falls back to exit-code-only pass/fail.
- **It runs on a repo you already have working locally** and does not reconstruct
  arbitrary environments from scratch — it relies on your local setup.
- **It needs your own API key**, and each real (non-`--offline`) run costs tokens.
- **Not a deterministic compiler, not a general CI service, and no guarantee a fix
  exists** for every task — it reports honest failure rather than faking success.
  One local repo per run. Full list in [`docs/SPEC.md`](docs/SPEC.md) §11.

---

## License

MIT — see [`LICENSE`](LICENSE).
