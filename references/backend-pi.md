# Pi Backend Notes

Pi runs through the SDK controller bundled with this skill:

```text
scripts/adapters/pi-agent-task.py   (controller)
scripts/adapters/pi-agent-bridge.mjs (Node SDK bridge)
```

The bundled `backends/pi.json` profile discovers the controller from that
location (override with dispatcher `--adapter` or the `PI_AGENT_TASK`
environment variable) and uses its `prompt` mode so every backend receives
the same review prompt and contract. It enables no tools for diff or
artifact review and only `read,grep,find,ls` for path review. The host must
provide the `pi` and `node` binaries and a valid Pi credential setup.

## Identity and effort

Omit provider, model, and effort to inherit Pi's configured defaults. When a
model is explicit, pass provider and model together — the profile marks the
provider and model capabilities, while the Pi adapter rejects a lone value.
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
