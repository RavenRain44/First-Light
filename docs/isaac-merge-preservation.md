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
