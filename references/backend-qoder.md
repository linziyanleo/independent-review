# Qoder CLI Backend Notes

Qoder runs through the canonical headless adapter from `using-qodercli`:

```text
~/.agents/skills/using-qodercli/scripts/qodercli-task.py
```

The bundled `backends/qoder.json` profile discovers that adapter (override with
dispatcher `--adapter` or the `QODERCLI_TASK` environment variable) and uses
its `prompt` mode with one private prompt file. It enables no tools for diff or
artifact review and only `Read,Grep,Glob` for path review. The adapter runs one
stateless `qodercli -p` task with `--permission-mode dont_ask`, zero
model-request retries, JSON validation, and no response file.

When multiple Qoder installations exist, select one before the model request:

```bash
python3 "$INDEPENDENT_REVIEW" review-paths \
  --backend qoder \
  --bin qodercli=/absolute/path/to/qodercli \
  --cwd "$REPO" \
  --paths 'src tests'
```

The profile requires the file name `qodercli` for any explicit or
environment-selected binary, prepends that binary's directory to the adapter
environment, then records the resolved absolute path and SHA-256 in its
normalized trace. Set `INDEPENDENT_REVIEW_QODERCLI_BIN` for a durable
non-secret default. Never infer authentication state from another Qoder
installation.

## Runtime environment

The profile declares the `login-zsh` environment hook. The dispatcher starts a
bounded interactive login zsh environment capture, which loads the user's
normal zsh startup sequence including `.zshrc`, then passes the captured
environment only in memory to the Qoder adapter. Shell startup stderr is not
mixed into the reviewer's strict result stream, and environment values are
never written to the normalized trace.

Use `--shell-env inherit`, or set `INDEPENDENT_REVIEW_QODER_SHELL_ENV=inherit`,
for CI and other processes whose environment is already authoritative. Loading
the shell environment is a pre-model step: a missing, failed, oversized, or
malformed environment is `outcome=not_started` with zero backend task
invocations.

## Identity and effort

Omit model and effort to use Qoder's configured/default selection. Pass an
explicit model with `--model`, effort with `--reasoning-effort`, and Qoder
agent with `--agent`; the profile declares these spellings. Qoder's adapter
defaults its agent when none is requested.

The current adapter does not expose a validated effective model, effort, or
session identity. Keep normalized effective identity absent rather than copying
requested values into trace.

## Authentication

Run the requested review without a login preflight. After, and only after, a
strong authentication-class failure, the adapter probes
`qodercli status --output json` once and exposes only the classified boolean
state:

- `logged_in`: transient or headless mismatch; do not request login.
- `logged_out`: ask the user to run `qodercli login` manually.
- `unknown`: preserve uncertainty.

Do not retry automatically in any of these cases.

Qoder's positional prompt transport can reach host argument-size limits for a
very large frozen artifact; the profile declares the `half-arg-max` prompt
limit so the dispatcher rejects oversized prompts before Qoder starts. Prefer a
smaller final net diff, `review-paths`, or another backend instead of
truncating evidence.
