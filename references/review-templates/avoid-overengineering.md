<!--
Template selection intent: use this template when the user asks whether a
change, plan, or design is overengineered, too complex, too abstract, harder
than necessary, or should be simplified. Match the user's meaning rather than
requiring these exact words. Use the default template for a broad correctness
review without a clear simplicity or overengineering focus.

These author notes guide semantic template selection and are removed before
the review rules are injected.
-->

Review for unnecessary complexity and overengineering while preserving every
demonstrated requirement, safety property, and durable architectural need.

Start with an answer-first assessment of whether the design is appropriately
sized. Then list findings by severity and finish with any evidence gaps. For
each finding, identify the concrete requirement being served, the complexity
that is not needed for that requirement, the present cost or risk it creates,
and the smallest simpler design that still works end to end.

Look especially for speculative abstractions, premature generalization,
unnecessary configuration or extension points, duplicated compatibility
paths, redundant fallbacks, indirection without a real boundary, and custom
infrastructure where an existing project mechanism is sufficient.

Do not treat modularity, explicit invariants, security boundaries, migration
safety, observability, or proven future requirements as overengineering merely
because they add code. Do not recommend a rewrite when the evidence only shows
a stylistic preference. When a simpler alternative depends on missing context,
state the evidence gap instead of presenting the simplification as a finding.
