# Result Contract

## Transport envelope

The dispatcher emits exactly one JSON object on stdout after a validated
backend result:

```json
{
  "type": "independent_review_result",
  "schema_version": 2,
  "outcome": "success",
  "invocation_id": "uuid",
  "backend": "<profile name>",
  "mode": "review-diff|review-paths|review-artifact",
  "requested": {
    "model": null,
    "effort": null,
    "provider": null,
    "agent": null
  },
  "defaults": {
    "backend": {"value": "<name>", "scope": "project|host|default"},
    "rounds": {"value": 1, "scope": "default"}
  },
  "review": {
    "verdict": "approve|request_changes|inconclusive",
    "text": "the reviewer's complete natural Markdown review"
  },
  "trace": {}
}
```

`requested` reports the effective identity asked of the backend after
remembered defaults were applied. Each key the memory filled appears in
`defaults` with its source scope; keys absent from `defaults` came from
explicit CLI flags. `defaults.rounds` is the remembered round budget — it is
advisory display for the host, not something the dispatcher enforces.

Do not infer the effective provider, model, effort, or agent from a requested
value. Backend trace fields report effective identity only when the backend's
validated envelope exposes it.

`trace.profile` records `{name, display_name, kind, source, sha256}` of the
profile that produced the result, so a review can be reproduced or audited
against the exact profile definition. `trace.ignored_defaults` lists
remembered `model`, `provider`, or `agent` values dropped because the backend
stayed `auto`.

Other trace fields a result may carry:

| Field | Meaning |
| --- | --- |
| `backend_task_invocations` | Always `1` on success; present on every runner path. Use it, not the exit code, for round and billing accounting. |
| `backend_trace` | The adapter envelope's own trace (envelope strategy only); may report effective identity. |
| `binaries` | `{name: {path, sha256}}` for binaries the profile marks `trace_sha256`; `path` is the validated absolute selection (including an intentional symlink), and adapter profiles with `adapter_flag` execute that exact selection. |
| `template` | Trusted review-template name, source (`bundled` or `user`), resolved path, and SHA-256. |
| `stderr` | Bounded backend stderr (argv kind only). |

The auxiliary commands emit their own JSON types on stdout:
`independent_review_backends` for `backends` and `independent_review_prefs`
for `prefs`. They share the failure diagnostic shape but are not review
envelopes.

On failure, stdout is empty and stderr contains one bounded JSON diagnostic.
Adapter failures preserve the adapter's validated `kind`, `outcome`, bounded
`details`, and exact `backend_task_invocations` count. A malformed adapter
diagnostic becomes `unknown` because billing/delivery state cannot be trusted.
Use these outcomes:

| Outcome | Meaning | Retry rule |
| --- | --- | --- |
| `not_started` | Input, profile, backend discovery, or local setup failed before a model task started | Fix the local cause; a later start is not a retry |
| `failed` | A known semantic backend, auth, permission, tool, or terminal failure occurred | Resolve the named cause before asking for a new invocation |
| `unknown` | Timeout, capture loss, invalid UTF-8, missing verdict, or uncertain delivery | Never retry automatically |

## Review payload

The reviewer's natural Markdown analysis is preserved in `review.text` without
coercing it into a rigid findings schema or rewriting its prose. The stdout
transport may normalize a terminal line ending; hosts judge the meaning and
evidence, not byte-for-byte formatting. The reviewer is free-form except for
one commitment: a short verdict statement at the beginning or the end using
exactly one of the words `approve`, `request_changes`, or `inconclusive`.

The dispatcher enforces exactly two payload rules:

- the text is non-empty and within the capture limit;
- a decisive verdict can be extracted. The extractor reads only line-level
  statements: a short labeled line whose tail is exactly one verdict word
  (`Verdict: …`, `Final verdict: …`, `裁决：…`), or a standalone
  verdict-word line. When no statement matches, it scans only the first and
  last five lines. Any conflict — two different verdict words across
  statements or within the edge window — and any absence is
  `outcome=unknown`: a hedging or ambiguous review is a delivery failure,
  never an approval, and the diagnostic preserves the paid review body
  (`result_bytes`, `result_sha256`, `result_excerpt`) for manual audit.

Everything else is judged semantically by the host during local disposition
rather than encoded as a dispatcher schema:

- `approve` claims no high or medium issue exists; `request_changes` claims at
  least one; `inconclusive` must name the concrete evidence gap.
- Every finding should carry a severity, concrete evidence (path plus line,
  function, symbol, or artifact section), the concrete incorrect behavior or
  risk, and the smallest fix or focused verification.
- Style-only findings are invalid review scope unless the caller explicitly
  requests style review.

## Local disposition

Do not write local dispositions into the reviewer payload. The host agent owns
acceptance and should report each material finding separately:

```text
finding: <title>
local_status: accepted | rejected | unverified
local_evidence: <path, command, test, or reason>
action: <fix performed, no change, or blocker>
```

Transport success, reviewer verdict, local disposition, and task acceptance
are four separate facts. A rebuttal round re-opens the verdict, never the
disposition ownership: the host still decides what to accept after the
reviewer re-judges a dispute.
