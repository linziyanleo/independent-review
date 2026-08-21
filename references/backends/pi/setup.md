# Pi Setup and Readiness

Use this guide for first use, authentication or binary changes, upgrades, or
readiness repair. For ordinary review behavior, return to
[runtime.md](runtime.md).

The host must provide compatible `pi` and `node` executables, a Pi SDK
installation resolvable by the selected `pi`, and a valid Pi credential setup.
The `backends` listing proves only that the two executables and bundled adapter
were discovered; it does not attest SDK compatibility, authentication, or
model access.

Before the first review:

1. Run `python3 scripts/independent-review.py backends` and confirm that `pi`
   is available.
2. If multiple installations exist, select the intended absolute `pi` and
   `node` paths with dispatcher `--bin` overrides. The controller uses those
   exact selections for SDK discovery and execution.
3. Complete authentication through the selected Pi installation's normal
   credential workflow. Do not copy, print, log, or commit credential values.
4. Run a small review only when one real model invocation is authorized; a
   successful result should carry validated effective provider, model, and
   thinking level plus the metadata-only receipt identifiers.

After changing either binary, credentials, the Pi SDK, or the selected model,
repeat discovery and one authorized smoke before relying on the backend for a
review gate.

## Adding a model provider (e.g. Qoder)

The bundled `pi.json` loads no extensions, so a provider that Pi normally
registers through an extension (such as `qoder`, added by
`@ali/qoder-compat-api-pi-plugin`) is not available under it. To use one, add a
host-local profile that points `adapter.provider_plugins` at the plugin module:

```json
"adapter": {
  "path_tools": {"flag": "--tools", "value": "read,grep,find,ls"},
  "timeout_flag": "--wall-timeout-seconds",
  "result": {"strategy": "envelope", "envelope_type": "pi_task_result"},
  "provider_plugins": [
    "~/.pi/agent/npm/node_modules/@ali/qoder-compat-api-pi-plugin/dist/index.js"
  ]
}
```

Save it as `${INDEPENDENT_REVIEW_HOME:-~/.config/independent-review}/backends/pi-qoder.json`
(never in the reviewed checkout), then select it explicitly with
`--backend pi-qoder --provider qoder --model <id>`. The adapter registers the
plugin's default export through a provider-only shim: it may add the model
provider but never tools, commands, or hooks, so the read-only, single-turn
contract is unchanged. The bundled `pi` profile stays hermetic.

Any local service the provider depends on must be running first — for Qoder,
start `qoder-compat serve` (default `http://127.0.0.1:8080`) so the plugin can
fetch its model catalog and route requests. A missing server surfaces as a
`pi_provider_plugin_failed` diagnostic with `outcome=not_started`.
