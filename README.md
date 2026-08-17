# independent-review

[中文文档](README.zh.md)

Run one independent, read-only review of code, diffs, or plans through a
configurable reviewer CLI backend. The review happens in a clean context,
separate from the session that authored the change, so the reviewer is free
of the authoring session's assumptions.

## Features

- **Backend-neutral** — reviewer CLIs are interchangeable JSON profiles, not
  hard-coded integrations. Bundled profiles: Pi, Qoder CLI, Codex CLI.
- **Three evidence modes** — `review-diff` (pasted diff), `review-paths`
  (named paths with read-only tool access), `review-artifact` (frozen
  documents such as plans or runbooks).
- **Remembered defaults** — backend, model, effort, and round preferences
  remembered per project, per host, and globally
  (`~/.config/independent-review/preferences.json`).
- **Bounded round budget** — one round is the default; every round is a
  separate billable invocation and the dispatcher never chains rounds on its
  own.
- **Adversarial acceptance** — structured findings you verify locally, with
  an optional rebuttal round for disputes that cannot be settled against the
  local tree.
- **Structured result contract** — a normalized result envelope with backend
  failure classification and explicit evidence gaps.

## Requirements

- Python 3.10+
- At least one supported reviewer CLI installed and authenticated on the
  host (e.g. `qodercli`, `codex`, or Pi)

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
  --artifact-file /path/to/plan.md
```

Remember preferences:

```bash
python3 "$DISPATCHER" prefs set --scope project --cwd "$REPO" --backend <name> --effort high
python3 "$DISPATCHER" prefs show
```

As an agent skill, install this repository under your skills directory
(e.g. `~/.agents/skills/independent-review`); `SKILL.md` is the entry point
for agent runtimes.

## Repository layout

```
SKILL.md            Skill entry point and operating contract
scripts/            Dispatcher (independent-review.py)
backends/           Reviewer CLI profiles (JSON)
references/         Profile schema, result contract, safety and retry rules
agents/             Agent definitions
tests/              Dispatcher tests (pytest)
```

## Running tests

```bash
python3 -m pytest tests/
```

## License

[MIT](LICENSE)
