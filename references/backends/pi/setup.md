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
