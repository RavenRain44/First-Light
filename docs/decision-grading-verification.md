# Decision grading verification

Read-only full-engine comparisons used disposable copies of the retained local database, no inference, downloads, cloud writes or notifications. The trial changed the facility-policy forecast gust advisory from 45 to 35 mph with assumed costs FP=1, FN=5. Neither the YAML registry nor any active policy was changed.

The pinned **7,470-day observation baseline** passed artifact/cohort verification with no input exclusions. After boundary purging, training contained 5,585 days and validation 939 days. Both incumbent and candidate produced identical classifications:

- Training: TP 194, TN 5,187, FP 0, FN 204; accuracy 96.35%, disruption recall 48.74%, weighted loss 1,020.
- Validation: TP 3, TN 908, FP 0, FN 28; accuracy 97.02%, disruption recall 9.68%, weighted loss 140.

The candidate was rejected because it did not reduce validation loss. Test results were deliberately not inspected. Changing a forecast threshold cannot improve an observation-only cohort without forecast inputs; the result illustrates why benchmark reconstruction matters and why high headline accuracy can hide missed disruptions.

This checkout has 12 retained archive-mode forecast evaluations. Only **six** satisfied the same-day 04:00, observed coverage and estimated issuance/availability checks. There were no eligible forecast training or validation days in the predefined periods, so this comparison was rejected for insufficient data. The UI labels these limitations. Restore/build the full forecast dataset before attempting live policy validation; the baseline cannot substitute for advance-warning evidence.

Verification passed **322 backend tests, 51 frontend unit checks, 20 browser checks**, and the production build. Synthetic backend checks cover append-only intentions/reviews, conflicting corrections, disputes, first-decision deduplication, missing/demo exclusions, exact confusion counts, empty/single-class denominators, assumed costs, DST boundaries, cached and concurrent inference, malformed/untrusted output, deidentification, bounded policy parameters, actual engine reruns, boundary purging, held-out selection independence, authorization, stale versions, restart recovery, activation and multi-step rollback, and cloud failure/retry/integrity/backup restoration.

Browser checks exercise objective annotation, observed calculation, manager grading and correction, separate error statistics, explicit Akamai explanation, proposal/evaluation/approval/activation/rollback at mobile and desktop widths with mocked APIs. Existing replay, chart, camera context and notification tests continue to run. All synthetic activation records live only in temporary test databases.

Remaining deployment checks: deploy the new code; configure the manager authorization token and manager login; verify actual Akamai response schema/latency under aggregate-only inputs; verify the private Object Storage prefix and restore on staging; restore the forecast archive; collect independently verified facility-action and objective outcomes before claiming closure accuracy, calibrated confidence, injury reduction or financial savings. No live threshold activation or real notification was performed.
