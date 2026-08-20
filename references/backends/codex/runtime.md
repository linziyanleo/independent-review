# Codex CLI Runtime Guide

Read [setup.md](setup.md) only for first use, authentication or binary changes,
upgrades, or readiness repair.

Codex runs through `codex exec`. The exact argv template lives in the bundled
`backends/codex.json` profile and invokes one ephemeral session with
`--sandbox read-only`, `--skip-git-repo-check`, `--ephemeral`, and `--json`.
The read-only sandbox is the write enforcement; no approval flags are passed
(current Codex CLI versions removed `--ask-for-approval` from `exec` — the
sandbox mode alone carries the posture). The dispatcher sends the prompt on
stdin, parses JSONL in memory, requires a completed turn and a non-empty final
agent message, then takes that message as the review text and extracts its
decisive verdict.

Override the binary with dispatcher `--bin codex=/path/to/codex` or the
`INDEPENDENT_REVIEW_CODEX_BIN` environment variable.

## Identity and effort

Omit model and effort to retain Codex's configured/default selection. Pass an
explicit model with `--model`. The profile spells explicit effort as the
versioned Codex configuration override `model_reasoning_effort`.

The Codex JSONL terminal stream does not currently provide one stable,
dispatcher-validated effective model and effort contract. Keep effective
identity absent unless a future profile revision validates those fields.

## Isolation

The read-only sandbox prevents normal workspace writes but is not a secrecy
boundary. Codex may still read repository content permitted by its process and
may load repository instructions. The generated prompt tells the backend not
to invoke another reviewer, use external agents, edit files, or perform remote
actions; this avoids recursive independent-review dispatch.

Do not edit the profile to pass `--dangerously-bypass-approvals-and-sandbox`,
enable web search, add writable directories, resume sessions, or apply
generated patches.

Treat a timeout, missing `turn.completed`, malformed JSONL, error event, or
lost final message as `outcome=unknown`. Do not rerun with another backend
merely to recover output.
