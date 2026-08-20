# DeepSeek Harness CLI (`dsh`) Backend Notes

## Status and selection

This bundled backend is **experimental and explicit-only**. It appears in the
`backends` listing, but its `auto_priority: null` keeps it out of implicit
`--backend auto`. Select it deliberately with `--backend dsh`.

The adapter and patch are source-verified against the current upstream CLI. An
installed-`dsh` end-to-end smoke has also succeeded; see the dated receipt
below. The backend remains explicit-only because readiness is host-local,
effective model identity is not yet attested in the result envelope, and dsh
is still developer-preview software.

`python3 scripts/independent-review.py backends` reports discovery readiness
only: it proves that the executable and adapter can be resolved. It does not
inspect the dedicated home's `headless` profile, provider bundle, settings, or
credential reference. Complete the readiness checks in this document before a
first model request on a host.

## Runtime contract

The host must provide an installed or built executable named `dsh` on `PATH`:

```text
dsh --profile headless --patch <skill>/scripts/adapters/dsh-review.patch.yml "<prompt>"
```

Override it with dispatcher `--bin dsh=/absolute/path/to/dsh` or
`INDEPENDENT_REVIEW_DSH_BIN`. The dispatcher resolves and traces the exact
binary; the adapter revalidates and executes that same path. A `pnpm dsh`
source checkout is intentionally not treated as an alternative runner because
`pnpm` alone does not prove that the requested backend exists.

The CLI accepts the task only as a positional argument. The adapter reads the
private dispatcher prompt file, rejects input above both half of host
`ARG_MAX` and a conservative 120 KiB single-argument ceiling, then passes one
bounded argv item. There is no stdin prompt or JSON terminal stream.

## Dedicated Harness home and identity

The adapter always replaces ambient `DSH_*` controls and supplies a dedicated,
trusted review home:

```text
${INDEPENDENT_REVIEW_DSH_HOME:-${INDEPENDENT_REVIEW_HOME:-~/.config/independent-review}/dsh}
```

It requires the review home and reviewed checkout to be disjoint after symlink
resolution; neither may contain the other. Use this home only for
independent-review configuration and do not point it at an ordinary dsh
authoring profile.

The profile, installed plugins, settings, and credentials are scoped to the
resolved `DSH_HOME`. Profiles are also independent of one another. Installing
a provider into the ordinary `~/.dsh` Web profile therefore does not make it
available in this dedicated home's `headless` profile.

## Provision the dedicated `headless` profile

Provisioning changes host-local configuration. Do it only when the user has
authorized that change, and use the exact home that the review adapter will
resolve:

```bash
REVIEW_DSH_HOME="${INDEPENDENT_REVIEW_DSH_HOME:-${INDEPENDENT_REVIEW_HOME:-$HOME/.config/independent-review}/dsh}"

DSH_HOME="$REVIEW_DSH_HOME" \
  dsh plugin --profile headless add <provider-package>@<pinned-version>
```

For the locally verified custom-provider route, the pinned installation was:

```bash
DSH_HOME="$REVIEW_DSH_HOME" \
  dsh plugin --profile headless add \
  @linziyanleo/dsh-custom-provider@0.1.1
```

Prefer a pinned published package for repeatable reviews. A local checkout may
be linked for provider development, but it makes the review runtime depend on
mutable source outside the Skill and is not the general setup.

`dsh` has no launcher flags for provider, model, reasoning effort, or agent
preset. The dispatcher profile therefore declares those identity fields as
unsupported. Configure provider/model/effort in the dedicated home's
`settings.yaml`. For `@linziyanleo/dsh-custom-provider`, the shape is:

```yaml
llm-custom:
  providers:
    example:
      displayName: Example Provider
      apiKeyEnv: EXAMPLE_API_KEY
      api: openai-completions
      baseURL: https://api.example.com/v1
      compat:
        supportsStore: false
        supportsDeveloperRole: false
        thinkingFormat: deepseek
        supportsReasoningEffort: true
        maxTokensField: max_tokens
        requiresReasoningContentOnAssistantMessages: true
      models:
        - id: example-model
          name: Example Model
          contextWindow: 262144
          maxTokens: 32768
          reasoningEfforts:
            high: high
            max: max

agent-default-model:
  provider: example
  model: example-model
  reasoningEffort: max
```

`agent-default-model.provider` selects a key under `llm-custom.providers`;
`agent-default-model.model` selects one of that route's model IDs; and
`agent-default-model.reasoningEffort` selects a key under that model's
`reasoningEfforts`. The value mapped from that key is what the provider sends
upstream. Omit `reasoningEffort` when the model does not declare reasoning
levels.

`apiKeyEnv` is a credential reference, not a place for a secret value. Make
the same reference available either through the dedicated home's credential
store or through an inherited environment variable. Credentials stored under
ordinary `~/.dsh` do not automatically cross into the dedicated home. Never
copy, print, log, or commit a credential value while provisioning or checking
the route.

Agent presets are a separate concern. Installing a custom provider changes the
model route; it does not add an `--agent-preset` selection path to the
headless runner. The current backend supports configured provider/model/effort
plus the task prompt, but it does not claim a selectable agent preset.

## Validate configuration before a paid review

First inspect the composed headless configuration under the same home:

```bash
DSH_HOME="$REVIEW_DSH_HOME" \
DSH_TELEMETRY_DISABLED=1 \
  dsh --profile headless --dump-config
```

Confirm that the selected server provider, settings service, credentials
service, and headless runner are present. Although `--dump-config` does not
boot a model turn, dsh may initialize or reconcile files and links inside the
profile. Treat it as a host-local write-capable readiness command in a managed
sandbox.

`pnpm peers check` can report dsh installation-owned peer packages as missing
because they are not direct dependencies of the out-of-tree profile. Do not
install duplicate peer packages solely to silence that static warning. The
composed config check plus one authorized end-to-end smoke are the runtime
gate.

For low-level diagnosis, the command shape executed by the adapter is:

```bash
SKILL_DIR=/absolute/path/to/independent-review

DSH_HOME="$REVIEW_DSH_HOME" \
DSH_AGENTS_HOME="$REVIEW_DSH_HOME/agents" \
DSH_PERMISSION_MODE=read-only \
DSH_TELEMETRY_DISABLED=1 \
  dsh --profile headless \
  --patch "$SKILL_DIR/scripts/adapters/dsh-review.patch.yml" \
  "<prompt>"
```

Normal Skill use should go through the dispatcher, which creates the scratch
workspace, strips ambient `DSH_*` controls, sets these fixed values, validates
the prompt bound, and classifies the result. The direct command above does not
reproduce that complete isolation contract:

```bash
python3 "$SKILL_DIR/scripts/independent-review.py" review-artifact \
  --backend dsh \
  --cwd "$REPO" \
  --artifact-file /path/to/artifact.md \
  --template default \
  --focus "Treat this as a transport smoke test and avoid speculative findings."
```

A live smoke is a real, potentially billable model request. Run it only with
explicit authorization. The dispatcher performs exactly one backend task
invocation and does not retry or switch backends automatically.

### Verified local receipt

On 2026-08-20, the dispatcher command above succeeded against installed dsh
`0.1.0-rc.7` with `@linziyanleo/dsh-custom-provider@0.1.1` in the dedicated
`headless` profile. It used the configured `routify` route,
`ds.deepseek-v4-pro`, and reasoning effort `max`; the result was `success` with
verdict `approve`, one backend task invocation, no retry, and invocation ID
`bb0c9abe-e3e5-4ddb-b948-afe71a65281e`.

This receipt proves that the dedicated profile, custom-provider bundle,
credential reference, model request, adapter, patch, and result extraction
worked together on that host at that time. It does not make those local
settings a Skill default and does not prove readiness on another host.

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

Upstream references:

- <https://github.com/deepseek-ai/deepseek-harness>
- <https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/README.md>
- <https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md>
