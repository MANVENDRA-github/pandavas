# pandavas

An autonomous multi-agent system that resolves a single coding task — one bug fix
or one feature — on a repository you already have checked out locally. Point it at
the repo, describe the task, and walk away. It researches the code, writes the
change, runs the tests, has a separate agent judge the result, and loops on that
feedback until the change passes or it reports — honestly — that it could not.

The name comes from the five Pandava brothers of the Mahabharata. Each agent is
mapped to the brother whose strongest trait fits the job, which also fixes the
hierarchy for free: the orchestrator is the eldest brother the others answer to.

## The core idea

LLM coding agents fail in a predictable way. The agent summarizes the code, the
summary is subtly wrong, and everything after that builds on the wrong summary —
including the agent's own claim that it's finished. pandavas is built around two
rules that go straight at that failure:

1. **A model never decides whether the code is correct.** The test runner is plain
   code: it runs the suite and reads exit codes and JUnit XML. Tests are the
   ground truth. The LLMs argue; the tests rule.
2. **Research hands over pointers, not prose, and every pointer is checked.** The
   research agent returns file paths with exact line ranges. Before any code is
   written, a deterministic gate confirms each anchor resolves to real lines in
   real files. A dangling anchor means research hallucinated, so the loop goes
   back — no worker ever builds on an unverified summary.

The judge, the regression guard, and the convergence loop all exist to keep those
two rules honest.

## The five agents

| Role             | Brother      | Does                                                                            |
|------------------|--------------|--------------------------------------------------------------------------------|
| Orchestrator     | Yudhishthira | Owns the shared state, runs the loop, decides converge / retry / stop.         |
| Research         | Nakula       | Explores the repo, returns an *anchored brief* — pointers and evidence, not prose. |
| Worker / Draft   | Arjuna       | Re-reads the real code at the anchors and writes the change (and a test).       |
| Test (execution) | Bhima        | Runs the suite. **Deterministic — not an LLM.** The ground truth.               |
| Judge / QA       | Sahadeva     | Fresh-context review of the diff and the true test state against the criteria.  |

## How it works

The orchestrator (Yudhishthira) is a LangGraph state machine, not a reasoning
agent — control flow over a typed `RunState`, nothing freeform. Before the loop
starts it captures a baseline test run and a snapshot of the repo. Then each
iteration runs:

1. **Research (Nakula)** builds a bounded, line-numbered view of the repo, ranks
   files against the task, and returns a typed `ResearchBrief`: acceptance
   criteria plus anchors (path, line range, snippet, why). The **resolve gate**
   then checks every anchor against the real files. Dangling or out-of-range
   anchors are fed back and research retries; if it still can't anchor its claims,
   the run stops and says so rather than guessing.
2. **Worker (Arjuna)** re-reads the actual code at those anchors — the snippets
   orient, they don't replace reading — and returns complete-file replacements.
   Edits go through a path-safe applier that refuses anything resolving outside the
   repo.
3. **Test (Bhima)** runs the suite as a subprocess in the repo's own environment.
   It auto-detects the command from the repo's manifests (`pytest`, `npm test`,
   `go test`, `cargo test`, `mvn test`), or you override it. It is regression-aware:
   it compares against the baseline and accepts a change only if it introduces no
   new failures. A test that passed at baseline and fails now is a regression and
   is rejected outright. Tests that go from failing to passing (red→green) are
   surfaced.
4. **Judge (Sahadeva)** runs with fresh context — it didn't write the code.
   Failing tests are rejected without spending a token, and so is an empty diff.
   Otherwise an independent model reviews the cumulative diff against the
   acceptance criteria and checks that any test the worker added actually encodes
   the requirement instead of passing vacuously.
5. **Loop.** The run converges when the tests pass *and* the judge approves.
   Otherwise the judge's specific feedback feeds the next worker pass. The
   orchestrator detects oscillation (the same change producing the same failures
   twice) and enforces a hard iteration cap. At the cap it restores the best
   attempt it saw — fewest new failures, then fewest failing tests — to disk,
   labels the run `did not converge`, and surfaces what's still failing. It never
   dresses a failing result up as a pass.

For a bug with no test covering it, the worker is asked to add a reproduction test
as part of the fix, so the repo ends up with a regression test it didn't have
before.

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/MANVENDRA-github/pandavas.git
cd pandavas
pip install -e .
```

That installs the runtime dependencies (`langgraph`, `openai`, `pydantic`,
`python-dotenv`) and makes the package runnable as `python -m pandavas`.

## Configuration

pandavas uses your own API keys and is built to run on free inference tiers. Copy
the template:

```bash
cp .env.example .env
```

Then set, in `.env`:

- `PANDAVAS_LLM_PROVIDER` — one of `groq`, `openrouter`, `gemini`, `openai`.
- The matching key — `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, or
  `OPENAI_API_KEY`.
- A pinned model id per agent — `PANDAVAS_RESEARCH_MODEL`, `PANDAVAS_WORKER_MODEL`,
  `PANDAVAS_JUDGE_MODEL`. Pin exact ids; never `latest` (reproducibility depends on
  it — see [Status and limits](#status-and-limits)).

The real `.env` is gitignored and never committed; only `.env.example` lives in the
repo. The client talks to any OpenAI-compatible endpoint, so the provider list in
`llm.py` is just a base-URL-and-key-name table — adding another compatible provider
is a one-line entry.

## Usage

```bash
python -m pandavas run --repo <path> --task "<description>" [options]
```

| Flag               | Required | Description                                                                                   |
|--------------------|----------|-----------------------------------------------------------------------------------------------|
| `--repo`           | yes      | Path to a local repository you already have working.                                          |
| `--task`           | yes      | Natural-language description of the bug or feature.                                            |
| `--test-command`   | no       | Override the auto-detected test command (e.g. `"pytest -q"`).                                  |
| `--max-iterations` | no       | Hard cap on retry iterations (default: `6`).                                                   |
| `--offline`        | no       | Use stub agents (no LLM, no API key) to check the install/wiring. The real executor still runs the tests. |
| `--report`         | no       | Path to write a JSON run report (summary, token usage, trace).                                |
| `--trace`          | no       | Path to write the full per-iteration JSON trace.                                              |
| `--junit-xml`      | no       | Path to a JUnit XML file your test command emits — per-test rigor for non-pytest frameworks. Relative paths resolve under `--repo`. |
| `--branch`         | no       | Branch name to commit a converged change to (default: auto from the task).                    |
| `--no-git`         | no       | Do not create a git branch/commit on a converged change.                                       |

The exit code is `0` if the run converged, `1` otherwise.

Check the install without an API key using `--offline`, which swaps in stub agents
(no LLM calls) but still runs the real test executor against your repo:

```bash
python -m pandavas run --repo . --task "smoke test" --offline
```

On a converged real run inside a git repo, pandavas commits the change to a new
branch named from the task (or `--branch`), so you get a reviewable diff. Pass
`--no-git` to skip that. A run prints an ASCII report:

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

If it can't converge, the report shows `status: did_not_converge`, a `reason:`
(`cap` or `oscillation`), and which iteration was the best attempt. `--report` and
`--trace` capture the machine-readable version.

There's also a self-contained demo that fixes a deliberately buggy fixture
(`tests/fixtures/sample_buggy_repo`) end to end with a scripted worker, so it needs
no API key:

```bash
python examples/demo.py
```

## Tests

```bash
python -m pytest
```

93 tests cover the deterministic core directly: the executor and test-command
detection, the JUnit parser, the resolve gate, the path-safe edit applier,
snapshot and diffing, the regression and red→green logic, oscillation and
best-attempt restore, the git helpers, the CLI, and an end-to-end red→green run on
the fixture. 92 run offline and pass; one is a live-API smoke test that runs only
when `GROQ_API_KEY` is set. CI runs the suite on Python 3.10, 3.11, and 3.12.

## Tech stack

- **Python 3.10+**
- **LangGraph** — the orchestrator is a compiled state graph over a typed `RunState`
- **OpenAI SDK** — one provider-agnostic client pointed at Groq, OpenRouter,
  Gemini's OpenAI-compatible API, or OpenAI, with bounded retry/backoff and token
  accounting
- **Pydantic v2** — the typed research brief and its validation
- **pytest** for the suite, **GitHub Actions** for CI

## Status and limits

The system is complete end to end: the deterministic executor, three real LLM
agents (research, worker, judge), the non-LLM test runner, and the state-machine
orchestrator are wired into the convergence loop, with regression-aware testing, a
CLI that does JSON reporting and token accounting, git delivery of a converged
change, and CI. What it deliberately does not do:

- **Output isn't deterministic.** The contract is moved from generation to
  acceptance: *produces a change that passes the gate, or reports that it could
  not* — not byte-identical output across runs. Pinned model strings, temperature
  0, and full per-iteration traces make a run debuggable, not reproducible to the
  byte.
- **Per-test regression rigor is native to pytest.** Other frameworks get it by
  emitting JUnit XML and passing `--junit-xml`; without parseable per-test results
  the gate falls back to exit-code pass/fail.
- **It runs on a repo that already works locally.** It doesn't reconstruct
  environments from scratch — it relies on your setup and the suite you already
  have.
- **No guarantee a fix exists.** When the loop can't converge it restores the best
  attempt and reports the failure plainly.
- **One local repo per run.** It isn't a CI service or a multi-repo tool.

One thing worth calling out honestly: the red→green signal comes from comparing
against the baseline run, not from running a fresh reproduction test against the
original code in isolation. That stricter pre-fix RED proof is noted as future
work.

The full design rationale lives in [`docs/SPEC.md`](docs/SPEC.md).

## License

MIT — see [`LICENSE`](LICENSE).
