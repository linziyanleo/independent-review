<!--
Template authoring notes; the dispatcher removes this comment before injection.

- A template contains only review-specific focus and output guidance. The
  dispatcher owns the fixed safety preamble, evidence fences, scope, and
  verdict contract.
- Add another trusted bundled template as <name>.md in this directory and
  select it with --template <name>. Names use lowercase letters, digits, and
  hyphens.
- Use balanced, non-nested HTML comments for author-facing explanations that
  must not reach the reviewer. A template must retain visible rules after all
  comments are removed.
- A host-local template with the same name under
  $INDEPENDENT_REVIEW_HOME/review-templates overrides the bundled template.
-->

Write the review as Markdown prose: an answer-first summary, then findings
ordered by severity (high, medium, low), then any evidence gaps.

Focus on correctness, security, data loss, concurrency, API contract drift,
missing tests, and deployment or operational risk. Ignore style-only comments
unless the caller explicitly includes style in the focus.

Every finding needs concrete evidence (path plus line, function, symbol, or
artifact section), the concrete incorrect behavior or risk, and the smallest
fix or focused verification.
