# Backend Integration Contract

How a reviewer CLI becomes an `independent-review` backend, and when it needs
an adapter. This is the decision document; the profile field schema lives in
[backend-profile.md](backend-profile.md).

## What the dispatcher needs from every backend

Six guarantees, regardless of integration shape:

1. **One-shot headless invocation** — no TUI, no interactive prompts, the
   process exits when the review is done.
2. **Read-only posture** — sandbox flags, tool allowlists, or permission
   modes that keep the reviewer from mutating anything; at minimum a
   prompt-level prohibition.
3. **Session isolation** — every invocation is a fresh, ephemeral context;
   no history, cache, or prior-session residue leaks into the review.
4. **Machine-readable terminal evidence** — a JSONL terminal event, a JSON
   envelope, or at minimum clean stdout with reliable exit codes, so the
   dispatcher can distinguish *delivered* from *lost*.
5. **Bounded output** — the dispatcher enforces capture limits, but the
   backend must not interleave progress noise into the result channel.
6. **Classifiable failure** — non-zero exits or structured diagnostics that
   separate `not_started` (local cause), `failed` (known semantic cause),
   and `unknown` (delivery uncertain).

## The decision rule

Ask of the CLI, in order:

1. Does it have a native one-shot headless mode?
2. Can the prompt arrive via stdin (or a file), not only as an argv
   positional?
3. Does it emit a machine-readable stream or envelope with an explicit
   terminal event?
4. Does that output match an existing dispatcher `result.strategy` without
   backend-specific parsing?
5. Can it be pinned read-only and session-isolated with flags alone?

Five yeses → `argv-stdin-jsonl`, **no adapter needed**. Any no →
`adapter-prompt-file` with a small adapter supplying the missing guarantees.

### Why Codex needs no adapter

`codex exec` answers all five natively: `exec` is one-shot, the prompt goes
on stdin, `--json` emits JSONL with `turn.completed`, and `--sandbox
read-only --ephemeral` pins posture and isolation.
The bundled `backends/codex.json` is pure configuration.

### Why Qoder CLI needs a wrapper adapter

`qodercli -p` exists, but the contract needs more than the raw CLI gives:
model-request retries disabled, a read-only tool allowlist, strict envelope
success semantics (`type=result`, `subtype=success`, `is_error=false`), an
auth-state probe after auth-class failures, selection among multiple
installations, and a prompt file because the positional prompt transport
hits host argument-size limits. The adapter adds **validation and failure
classification**, not invocation.

### Why Pi needs an SDK controller

Pi exposes an Agent SDK, not a one-shot CLI. The bundled controller
(`scripts/adapters/pi-agent-task.py`) drives the SDK through a Node bridge
(`pi-agent-bridge.mjs`), disables sessions, ambient extensions, compaction,
and retries, and validates terminal events, tool pairing, and effective
identity before emitting its envelope.

## The adapter contract

The dispatcher invokes an adapter exactly one way:

```text
{python} <adapter> prompt --cwd <dir> --prompt-file <private 0600 file>
  [<profile binary adapter_flag> <resolved absolute path>]...
  [--tools <profile path_tools>] [--model M] [--effort E]
  [--provider P --model M] [--agent A] [--timeout-seconds N]
```

An adapter must:

- read the prompt from the prompt file (never from argv) and run exactly one
  backend task, honoring the read-only scope and the flags it accepts;
- revalidate every explicit binary path after any login-shell environment
  capture and execute that exact path, never a fresh `PATH` lookup; a missing,
  replaced, non-file, or non-executable path is `not_started` with zero backend
  task invocations;
- on success, print either the review text itself (`stdout-text` strategy)
  or one JSON envelope (`envelope` strategy):
  `{"type": "<envelope_type>", "result": "<review text>", "trace": {"outcome": "success", ...}}`;
- print nothing on stderr on success — any stderr output is treated as
  `unknown`;
- on failure, exit non-zero and print one bounded JSON diagnostic on stderr:
  `{"type":"independent_review_adapter_diagnostic","kind":"...",`
  `"outcome":"not_started|failed|unknown","backend_task_invocations":0|1,`
  `"details":{...}}`; the dispatcher validates this exact shape and preserves
  its classification and invocation count;
- forward its own graceful timeout when given the profile's timeout flag;
  the dispatcher still holds an outer guard (forwarded value + margin), and
  enforces the effective timeout directly when the profile cannot forward;
- never write response files, print environment values, or perform external
  actions beyond the single model task.

## Adding a backend: checklist

1. Run the decision rule above; pick `argv-stdin-jsonl` or
   `adapter-prompt-file`.
2. Write the profile per [backend-profile.md](backend-profile.md) into
   `~/.config/independent-review/backends/` (or bundle it).
3. If an adapter is needed, place it under `scripts/adapters/` and point
   `discovery.adapter.candidates` at it; the dispatcher's `--adapter` flag
   and the profile's `env` override remain available for development.
4. Confirm `python3 scripts/independent-review.py backends` reports the
   backend available, then run one `review-diff` against a small real diff.
5. Record quirks (auth behavior, output shapes, prompt limits) in a
   `references/backend-<name>.md` notes file and set the profile's `notes`.
