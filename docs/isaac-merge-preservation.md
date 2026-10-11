# Isaac merge preservation checklist

This records the Isaac behavior before merging origin/integration.

- Akamai generates email and SMS automatically when a new notification package is created from a recorded manager decision.
- Generated wording is persisted, reused when reopening the package, and editable. Failed generation preserves the editable template and records inference failure details.
- Per-group and bulk Akamai regeneration remain available. The recorded human decision and group reporting instructions remain authoritative.
- Every recipient group requires review and approval before dispatch. Edits invalidate approval.
- Recipient routing respects dated assignments, telework, leave, workdays, essential duties, and accessibility follow-up.
- Durable notification packages, append-only audits, scheduling, retries, and superseding updates are retained.
- Normal delivery is simulation. Real SMTP tests require explicit action and locally allowlisted contacts.
- Akamai decision briefs use bounded structured requests, evidence validation, and deterministic fallback; AWS brief fallback is opt-in.
- The staff notification composer remains reachable from the dashboard workflow.

Pre-merge verification from the implementation: 119 backend tests passed; frontend production build passed; a synthetic live Akamai request generated email and SMS successfully without sending staff messages.

When integration offers a conflicting feature or workflow, ask the user which behavior takes precedence before resolving it. Compatible additions can be combined.

## Approved merge decisions

The user selected integration's notification workflow and redesigned dashboard. Those choices supersede the pre-merge separate email/SMS composer and its per-group/bulk generation controls. The earlier implementation remains in commit fc04f78.

The merged notification workflow uses editable location, decision and instruction fields with Akamai weather wording and package-wide regeneration. Manager review, approval, recipient routing, saved drafts, audits, scheduling, simulation and explicit SMTP tests are retained. Integration's past decisions, cameras, replay improvements, storage and deployment support are included.

Strands on Amazon Bedrock replaces direct Bedrock fallback but remains opt-in: STRANDS_FALLBACK_ENABLED defaults to false. Setting it to true explicitly enables the fallback. Akamai remains the primary provider.

Merge validation: 168 backend tests passed, 20 frontend tests passed, and the frontend production build succeeded. Regression coverage verifies that Strands fallback is disabled when unset or false and enabled only when explicitly true.
