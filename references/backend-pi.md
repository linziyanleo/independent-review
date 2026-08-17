# Pi Backend Notes

Pi runs through the canonical controller from `using-pi-agent`:

```text
~/.codex/skills/using-pi-agent/scripts/pi-agent-task.py
```

The bundled `backends/pi.json` profile discovers that controller (override with
dispatcher `--adapter` or the `PI_AGENT_TASK` environment variable) and uses
its `prompt` mode so every backend receives the same review prompt and JSON
contract. It enables no tools for diff or artifact review and only
`read,grep,find,ls` for path review.

## Identity and effort

Omit provider, model, and effort to inherit Pi's configured defaults. When a
model is explicit, pass provider and model together — the profile marks the
provider as requiring the model, and the dispatcher rejects a lone provider.
Pass an explicit effort as Pi `--effort`; never guess an unspecified effort.

Pi validates and returns effective provider, model, and thinking level in its
`pi_task_result` envelope. Preserve those values in the normalized trace.

## Runtime contract

Run the Python controller itself in the environment that owns Node, the Pi SDK,
credentials, and network access. Do not split the controller and parser across
shell pipes, redirections, or separate privilege boundaries.

The controller disables persistent sessions, ambient Pi extensions and skills,
compaction, agent retries, and provider retries. It validates terminal events,
read-only tool pairing, stop reason, selected identity, and non-empty result.
It also maintains a metadata-only receipt. Preserve its `invocation_id`,
`pi_session_id`, and `receipt_path` in the normalized trace.

Pi distinguishes whole-task, provider-request, and stream-idle timeouts. The
profile declares no dispatcher timeout and forwards an override only when the
caller explicitly sets `--timeout-seconds`; otherwise retain Pi's safe
mode-dependent profiles.

On an ambiguous Pi result, preserve its original diagnostic and do not start a
second backend.
