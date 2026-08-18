# Backend Profile Specification

A backend profile is one JSON object that adapts a reviewer CLI to the
independent-review contract. Read
[backend-integration.md](backend-integration.md) first for the decision rule
(no adapter vs. wrapper vs. SDK controller) and the adapter contract; this
document is the field-level schema.

The dispatcher loads profiles from exactly two trusted directories, never
from the reviewed repository:

1. `${INDEPENDENT_REVIEW_HOME:-~/.config/independent-review}/backends/*.json`
   (user profiles; a user profile with the same `name` replaces the bundled
   one entirely — there is no field-level merge)
2. `<skill>/backends/*.json` (bundled defaults shipped with the skill)

Adding a reviewer that fits an existing `kind` is a pure configuration task:
drop a profile into the user backends directory. A new `kind` is the only
extension that requires dispatcher code.

## Top-level fields

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | `1` | Profile format version. Required. |
| `name` | string | `^[a-z0-9][a-z0-9-]*$`; the value passed to `--backend`. Required. |
| `display_name` | string | Human label used in listings. Required. |
| `kind` | string | Invocation shape: `adapter-prompt-file` or `argv-stdin-jsonl`. Required. |
| `auto_priority` | integer (not boolean) | Bundled profiles join `--backend auto` in ascending order. User profiles never join implicit auto; name them in `INDEPENDENT_REVIEW_BACKENDS` to opt in. Required. |
| `discovery` | object | How the dispatcher finds binaries and the adapter. Required. |
| `identity` | object | Which of `provider`, `model`, `effort`, `agent` the backend accepts, and how to spell them. Required (any entry may be `null`). |
| `timeouts` | object | `{"review-paths": seconds-or-null, "default": seconds-or-null}`. `null` means no dispatcher timeout. Required. |
| `notes` | string | Skill-relative path to the backend's quirks document. Optional. |
| `command` | array | argv template. Required for `argv-stdin-jsonl` only. |
| `adapter` | object | Adapter behavior knobs. Required for `adapter-prompt-file` only. |
| `result` | object | Extraction strategy. Required for `argv-stdin-jsonl`; for adapters it lives under `adapter.result`. |

## discovery

```json
"discovery": {
  "binaries": {
    "qodercli": {
      "env": "INDEPENDENT_REVIEW_QODERCLI_BIN",
      "basename": "qodercli",
      "adapter_flag": "--qodercli-bin",
      "trace_sha256": true
    }
  },
  "adapter": {
    "env": "QODERCLI_TASK",
    "candidates": ["{skill_dir}/scripts/adapters/qodercli-task.py"]
  }
}
```

- Every key in `binaries` must resolve for the backend to count as available.
  Resolution order: dispatcher `--bin <name>=<path>`, then the named
  environment variable, then `PATH` lookup.
- `basename`: an explicit `--bin`/env path must carry this exact file name.
  Prevents pointing a profile's trust assumptions at an arbitrary binary.
- `adapter_flag`: for `adapter-prompt-file`, pass the resolved absolute path as
  `<adapter_flag> <path>` so discovery, execution, and trace refer to the same
  executable. Adapter flags must be unique inside one profile and are invalid
  for argv profiles, which use `{bin:<name>}` placeholders instead.
- `prepend_to_path`: the resolved binary's directory is prepended to the
  child process `PATH`. This is optional supporting environment setup, not an
  exact binary-selection mechanism; use `adapter_flag` when the adapter starts
  the declared executable.
- `trace_sha256`: the resolved binary's absolute path and SHA-256 are recorded
  in the normalized trace.
- `adapter` is required for `adapter-prompt-file` profiles. `env` overrides the
  path; otherwise the first existing `candidates` entry wins. `{skill_dir}`
  expands to the resolved skill root. Dispatcher `--adapter` beats both.

## identity

Each entry is either `null` (the dispatcher rejects the corresponding flag
for this backend) or one of:

```json
"model":  {"flag": "--model"}
"effort": {"args": ["--config", "model_reasoning_effort=\"{effort}\""]}
```

- `flag`: append `<flag> <value>` when the caller supplies the value.
- `args`: append the rendered template (`{model}`, `{effort}`, `{provider}`,
  `{agent}` expand). Use this for non-flag spellings such as Codex config
  overrides.

`effort` values are constrained globally to the dispatcher's vocabulary —
`off|minimal|low|medium|high|xhigh|max` — on the CLI, in remembered
defaults, and therefore for every profile; a backend whose effort words
differ needs the mapping inside its own adapter. Backend-specific identity
pairing belongs in that backend's adapter; for example, Pi rejects a lone
provider itself rather than imposing that rule on every profile.

## kind: adapter-prompt-file

The dispatcher runs:

```text
{python} <adapter> prompt --cwd {cwd} --prompt-file <private 0600 file>
  [<binary adapter_flag> <resolved absolute path>]...
```

`adapter` section fields:

| Field | Meaning |
| --- | --- |
| `path_tools` | `{"flag", "value"}` appended only in `review-paths` mode; `null` for none. |
| `timeout_flag` | Flag used to forward the effective whole-task timeout; `null` to never forward. |
| `result.strategy` | `envelope` or `stdout-text`. |
| `result.envelope_type` | For `envelope`: required `type` value of the adapter's JSON envelope. The envelope must carry a string `result` containing the review text and a `trace.outcome == "success"`. |

An adapter that accepts a declared binary flag must revalidate the path before
the backend task starts and execute that exact path; it must not replace the
selection with a later `PATH` lookup. Transport quirks such as login-shell
capture, argv-size limits, and identity pairing remain adapter
responsibilities. Adapter-kind rules baked into the dispatcher: a non-zero
exit must carry the standard diagnostic from
[backend-integration.md](backend-integration.md); malformed diagnostics become
`outcome=unknown`. Any stderr output on a zero exit is likewise `unknown`;
review text must be non-empty and carry a decisive verdict.

Every object layer is fail-closed: unknown top-level, `discovery`, `adapter`,
`result`, `identity`, binary-spec, path-tool, or timeout fields invalidate the
whole profile. A typo never silently degrades a safety setting.

## kind: argv-stdin-jsonl

The dispatcher renders the profile's `command` template, sends the prompt on
stdin, and reads JSONL events from stdout. Placeholders: `{bin:<name>}`,
`{cwd}`, `{python}`.

`result.strategy`:

- `jsonl-terminal-message`: require a `turn.completed` event, reject `error` /
  `turn.failed`, take the last completed `agent_message` item text as the
  review text.

Argv-kind rules baked in: a non-zero exit, timeout, missing terminal event,
or lost final message is `outcome=unknown`; stderr is captured into the trace,
never treated as a diagnostic channel.

## timeouts

`{"review-paths": 2400, "default": 1200}` picks the whole-task timeout by
mode; `null` disables it (use when the backend owns safe mode-dependent
profiles, as Pi does). An explicit dispatcher `--timeout-seconds` always
wins.

For `adapter-prompt-file` profiles the effective timeout is forwarded through
`timeout_flag` so the adapter can shut down gracefully; the dispatcher still
holds an outer guard (forwarded value plus a fixed margin). When the profile
cannot forward (`timeout_flag: null`), the effective value becomes the
dispatcher guard directly, so a hung adapter can never block the host
forever and an explicit `--timeout-seconds` is never silently dropped.

## Safety rules for profiles

- Profiles are executable command definitions. Load them only from the two
  trusted directories above. Refuse any profile found inside the reviewed
  checkout.
- Keep profiles free of secrets: no tokens, no credential paths, no
  environment dumps.
- A profile selects and spells behavior; it must not widen the reviewer's
  authority. Never add sandbox bypasses, writable mounts, approval prompts,
  session resume, or network-enabling flags.
