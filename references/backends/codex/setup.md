# Codex CLI Setup and Readiness

Use this guide for first use, authentication or binary changes, upgrades, or
readiness repair. For ordinary review behavior, return to
[runtime.md](runtime.md).

The host must provide an authenticated `codex` executable compatible with the
argv and JSONL contract in `backends/codex.json`. The `backends` listing proves
only that the executable was discovered; it does not attest authentication,
model access, or terminal-event compatibility.

Before the first review:

1. Run `python3 scripts/independent-review.py backends` and confirm that
   `codex` is available.
2. If multiple installations exist, select the intended absolute binary with
   dispatcher `--bin codex=/absolute/path/to/codex` or the non-secret
   `INDEPENDENT_REVIEW_CODEX_BIN` setting.
3. Complete authentication through that Codex installation's normal host
   workflow. The review workflow must not open a browser or log in for the
   user, and diagnostics must not print credential values.
4. Run a small review only when one real model invocation is authorized and
   confirm that it produces a completed JSONL turn with a non-empty final
   message.

After changing the executable, authentication, or Codex version, repeat
discovery and one authorized smoke before relying on the backend for a review
gate.
