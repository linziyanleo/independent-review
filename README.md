# independent-review

[中文文档](README.zh.md)

Run one independent, read-only review of code, diffs, or plans through a
configurable reviewer CLI backend. The review happens in a clean context,
separate from the session that authored the change, so the reviewer is free
of the authoring session's assumptions.

## Features

- **Backend-neutral** — reviewer CLIs are interchangeable JSON profiles, not
  hard-coded integrations. Bundled profiles: Pi, Qoder CLI, Codex CLI, and
  DeepSeek Harness CLI (`dsh`, experimental).
- **Three evidence modes** — `review-diff` (pasted diff), `review-paths`
  (named paths with read-only tool access), `review-artifact` (frozen
  documents such as plans or runbooks).
- **Remembered defaults** — backend, model, effort, and round preferences
  remembered per project, per host, and globally
  (`~/.config/independent-review/preferences.json`).
- **Bounded round budget** — one round is the default; every round is a
  separate billable invocation and the dispatcher never chains rounds on its
  own.
- **Adversarial acceptance** — every material finding is verified locally
  before acceptance; disputes that cannot be settled against the local tree
  escalate to a rebuttal round.
- **Hybrid review contract** — the reviewer's natural Markdown analysis is
  preserved without forcing it into a findings schema, plus one extracted
  decisive verdict. A conflicting or missing verdict is an `unknown` delivery
  failure, never a silent approval, and the diagnostic preserves the review
  body for semantic audit.

## Requirements

- Python 3.10+
- At least one supported reviewer CLI installed and authenticated on the
  host (`qodercli`, `codex`, `dsh`, or `pi` + `node`). All glue adapters are
  bundled under `scripts/adapters/` — the skill has no external skill
  dependencies.

## Usage

```bash
DISPATCHER=scripts/independent-review.py

# List discovered backend profiles and their availability
python3 "$DISPATCHER" backends

# Review a final diff
python3 "$DISPATCHER" review-diff \
  --backend auto --cwd "$REPO" --diff-file /path/to/final.diff

# Review named paths with read-only tool access
python3 "$DISPATCHER" review-paths \
  --backend <name> --cwd "$REPO" --paths 'src/auth tests/auth'

# Review a frozen artifact (plan, spec, runbook)
python3 "$DISPATCHER" review-artifact \
  --backend <name> --effort high --cwd "$REPO" \
  --artifact-file /path/to/plan.md --template default

# Escalate an unresolved dispute back to the same reviewer
python3 "$DISPATCHER" review-diff \
  --backend <name> --cwd "$REPO" --diff-file /path/to/final.diff \
  --rebuttal-file /path/to/rebuttal.md
```

The experimental `dsh` profile is explicit-only: it is listed by `backends`
but never selected by implicit `auto`. Its isolated-home setup, identity
configuration, and current limitations live in
[references/backend-dsh.md](references/backend-dsh.md), not in the skill
workflow.

Remember preferences per project, per host agent, or globally:

```bash
python3 "$DISPATCHER" prefs set --scope project --cwd "$REPO" --backend <name> --effort high
python3 "$DISPATCHER" prefs set --scope host --host kimi-code --rounds 2
python3 "$DISPATCHER" prefs resolve --cwd "$REPO" --host kimi-code
python3 "$DISPATCHER" prefs show
```

As an agent skill, install this repository under your skills directory
(e.g. `~/.agents/skills/independent-review`); `SKILL.md` is the entry point
for agent runtimes.

## Interpret the result

Treat the verdict as evidence, not acceptance. `review.text` carries the
reviewer's full analysis; verify every high and medium finding against the
current local tree and record a disposition (`accepted`, `rejected`, or
`unverified`) before acting on it. See
[references/result-contract.md](references/result-contract.md) for the
envelope shape, failure outcomes, and retry rules.

## Add a reviewer

Drop a JSON profile into `~/.config/independent-review/backends/` — no code
changes needed when the CLI fits an existing profile `kind`:

```json
{
  "schema_version": 1,
  "name": "mycli",
  "display_name": "My CLI",
  "kind": "argv-stdin-jsonl",
  "auto_priority": 90,
  "discovery": {"binaries": {"mycli": {}}},
  "command": ["{bin:mycli}", "run", "--json", "--cd", "{cwd}", "-"],
  "identity": {"model": {"flag": "--model"}},
  "result": {"strategy": "jsonl-terminal-message"},
  "timeouts": {"default": 1200}
}
```

`jsonl-terminal-message` expects Codex-style events (`turn.completed` plus
`agent_message` items); CLIs with other output shapes plug in through a small
adapter (`adapter-prompt-file`). See
[references/backend-profile.md](references/backend-profile.md) for the full
schema and [references/candidate-backends.md](references/candidate-backends.md)
for researched invocation notes on several popular CLIs.

## Add a review type

Drop `<name>.md` into
`~/.config/independent-review/review-templates/`, then pass
`--template <name>`. A template contains only review-specific focus and output
guidance; the dispatcher keeps the fixed safety preamble, input fences, scope,
and verdict contract. User templates are never loaded from the reviewed
checkout.

## Safety

- The reviewer is read-only; pasted-content modes expose no tools at all.
- Exactly one billable invocation per round; `unknown` outcomes are never
  retried automatically.
- Profiles and preferences load only from the skill and the user
  configuration home — never from the reviewed checkout.
  See [references/safety-and-retry.md](references/safety-and-retry.md).

## Repository layout

```
SKILL.md            Skill entry point and operating contract
scripts/            Dispatcher (independent-review.py) and bundled adapters (adapters/)
backends/           Reviewer CLI profiles (JSON)
references/         Contracts, backend notes, and bundled review templates
agents/             Agent definitions
tests/              Dispatcher tests (unittest)
```

## Running tests

```bash
python3 -m unittest discover -s tests
```

## License

[MIT](LICENSE)
