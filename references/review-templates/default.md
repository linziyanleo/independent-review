Write the review as Markdown prose: an answer-first summary, then findings
ordered by severity (high, medium, low), then any evidence gaps.

Focus on correctness, security, data loss, concurrency, API contract drift,
missing tests, and deployment or operational risk. Ignore style-only comments
unless the caller explicitly includes style in the focus.

Every finding needs concrete evidence (path plus line, function, symbol, or
artifact section), the concrete incorrect behavior or risk, and the smallest
fix or focused verification.
