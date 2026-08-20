# DeepSeek Harness CLI (`dsh`) Setup and Readiness

Use this guide for first use, provider or credential changes, upgrades, or
readiness repair. For ordinary review behavior, return to
[runtime.md](runtime.md).

## Dedicated Harness home and identity

The adapter always replaces ambient `DSH_*` controls and supplies a dedicated,
trusted review home:

```text
${INDEPENDENT_REVIEW_DSH_HOME:-${INDEPENDENT_REVIEW_HOME:-~/.config/independent-review}/dsh}
```

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
model route; it does not add an `--agent-preset` selection path to the headless
runner. The current backend supports configured provider/model/effort plus the
task prompt, but it does not claim a selectable agent preset.

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

After a dsh or provider upgrade, re-verify the adapter/patch against the
installed source contract, re-run the composed configuration check, and obtain
authorization for a new live smoke before treating the backend as ready.

Upstream references:

- <https://github.com/deepseek-ai/deepseek-harness>
- <https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/README.md>
- <https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md>
