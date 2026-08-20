# DeepSeek Harness CLI (`dsh`) Runtime Guide

Read [setup.md](setup.md) only for first use, provider or credential changes,
upgrades, or readiness repair.

## Status and selection

This bundled backend is **experimental and explicit-only**. It appears in the
`backends` listing, but its `auto_priority: null` keeps it out of implicit
`--backend auto`. Select it deliberately with `--backend dsh`.

The adapter and patch are source-verified against the current upstream CLI. An
installed-`dsh` end-to-end smoke has also succeeded; the dated receipt is in
[setup.md](setup.md#verified-local-receipt). The backend remains explicit-only
because readiness is host-local, effective model identity is not yet attested
in the result envelope, and dsh is still developer-preview software.

`python3 scripts/independent-review.py backends` reports discovery readiness
only: it proves that the executable and adapter can be resolved. It does not
inspect the dedicated home's `headless` profile, provider bundle, settings, or
credential reference. Follow [setup.md](setup.md) before a first model request
on a host.

## Runtime contract

The host must provide an installed or built executable named `dsh` on `PATH`:

```text
dsh --profile headless --patch <skill>/scripts/adapters/dsh-review.patch.yml "<prompt>"
```

The bundled profile discovers `scripts/adapters/dsh-task.py`; override that
selection for development with dispatcher `--adapter` or the `DSH_TASK`
environment variable.

Override it with dispatcher `--bin dsh=/absolute/path/to/dsh` or
`INDEPENDENT_REVIEW_DSH_BIN`. The dispatcher resolves and traces the exact
binary; the adapter revalidates and executes that same path. A `pnpm dsh`
source checkout is intentionally not treated as an alternative runner because
`pnpm` alone does not prove that the requested backend exists.

The CLI accepts the task only as a positional argument. The adapter reads the
private dispatcher prompt file, rejects input above both half of host
`ARG_MAX` and a conservative 120 KiB single-argument ceiling, then passes one
bounded argv item. There is no stdin prompt or JSON terminal stream.

The adapter replaces ambient `DSH_*` controls and supplies the dedicated,
trusted review home configured in [setup.md](setup.md). It requires the review
home and reviewed checkout to be disjoint after symlink resolution; neither
may contain the other. Do not point it at an ordinary dsh authoring profile.

## Independent review posture

Every mode starts dsh in a newly created empty scratch workspace. This keeps
the reviewed checkout's `.env`, `AGENTS.md`, `CLAUDE.md`, project skills, and
other launcher-owned context out of boot. For `review-paths`, the adapter adds
the resolved repository root to the trusted task context so relative paths and
symbols can still be inspected from the scratch workspace.

The last-applied `dsh-review.patch.yml` overlay:

- replaces the authoring persona with a backend-neutral review persona;
- disables repository instructions, skill discovery/catalogs, Code Mode,
  shell/jobs, mutation helpers, goals, plan mode, workflows, delegation,
  model-backed session titles, and web search;
- leaves only dsh's filesystem/search package for path discovery and reads.

The adapter forces `DSH_PERMISSION_MODE=read-only`, so write/edit operations
that share dsh's filesystem tool package are rejected by the sandbox. It also
forces `DSH_TELEMETRY_DISABLED=1`.

## Output and failure handling

On a completed turn, dsh exits 0 and writes the final assistant text to stdout.
The adapter requires non-empty stdout and empty stderr, then passes the natural
review text to the dispatcher's verdict extraction. A non-zero exit has no
structured terminal event, so the adapter conservatively reports whether the
task demonstrably failed or whether its outcome is unknown; it never retries.
Authentication-class diagnostics direct the user to the credential reference
required by the selected provider; they do not assume a built-in provider or a
specific environment-variable name.

Fresh sessions persist under the dedicated home's `sessions/` directory but
are never resumed by the adapter.

## Current limitations

- Backend discovery does not attest dedicated-profile or credential readiness.
- The result envelope reports the dispatcher-requested provider, model, effort,
  and agent as `null`, because those values are configured inside dsh rather
  than passed through supported dispatcher flags. The dated smoke identifies
  the effective route from the controlled local configuration, not from an
  end-to-end identity attestation in the result.
- Headless agent-preset selection is not wired into this backend. Provider
  configuration and agent presets remain orthogonal.
- Dsh's read-only sandbox confines mutations, not arbitrary reads, network, or
  process visibility. The overlay removes known shell, delegation, and web
  capabilities, but upstream can add new model-facing plugins; re-audit the
  overlay when upgrading dsh.
- The filesystem plugin exposes read and write/edit schemas together. The
  write/edit calls remain visible to the model even though read-only sandbox
  policy rejects them.
- The positional prompt cap is much smaller than the dispatcher's general
  input cap. Large frozen diffs or artifacts must use another backend.
- Dsh is developer-preview software; flags, bundles, and patch row IDs can
  change. A version upgrade requires source-contract verification and a live
  smoke before enabling implicit auto selection.
