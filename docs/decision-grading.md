# Decision grading and controlled policy tuning

Open **Decision log → Grade decision**. Review the original saved recommendation, reasons, rule version, manager call and reasoning. Optionally record an intended objective when confirming a new decision. Adding an objective later is explicitly marked retrospective with its own timestamp; corrections append records and require a reason.

The three assessments are separate:

- **Agreement:** whether the manager chose the original recommended posture. Agreement is not accuracy.
- **Objective achieved:** the manager reports achieved, partly achieved, not achieved or unknown. These opinions never supply statistical or training labels.
- **Calculated weather assessment:** an independent completed-day local weather benchmark classifies the call and original recommendation. It does not prove that closing was necessary or establish correct arrival/dismissal times.

Manager grades are good call, too lenient, too strict, mixed or insufficient evidence. Evidence links are recorded references, not automatic verification. A manager can dispute the observed weather evidence; the affected day is excluded from statistics until a versioned review resolves the dispute. This does not rewrite archive observations. Concurrent edits receive a conflict and preserve both existing records. Repeated clicks cannot overwrite a review or intention.

## Observed evidence and statistics

**Calculate from observed weather** explicitly retrieves the completed local day from IEM ASOS and nearby NWS storm reports. It never invokes inference. Pending days cannot be graded. Coverage needs temperature and wind observations in at least 87.5% of the day’s hours and no gap longer than three hours; archive requests must succeed. Local midnight boundaries account for 23/25-hour DST days. The next day's observations are excluded. Archive outages are displayed rather than interpreted as quiet weather.

`completed-weather-v1` identifies local weather disruption from a nearby tornado report, gust ≥58 mph, recorded corridor rank ≥3, freezing precipitation ≥2 hours, a snow report ≥6 inches, or ice ≥0.1 inch. This is a weather benchmark, not an office-open/closed label. It differs from the historical station-only `AMW-local-disruption-v1` benchmark; their metrics remain separate.

The **Decision feedback & error analysis** panel updates on demand and after returning from grading. A hash of the immutable feedback rows, historical records, frozen manifest, activation and cost scenario caches each metric run. It keeps only the first real decision per facility/local day in operational error statistics, rather than choosing a better later call with hindsight. Demo/example, non-live, pending, disputed, insufficient observations and insufficient/unrecorded decision-time evidence are excluded with counts and reasons.

A non-normal posture is a binary warning. Observed disruptive weather is the positive label. TP is a caught disruption, TN a correctly quiet day, FP a false alarm (Type I), and FN a missed disruption (Type II). The panel provides accuracy, balanced accuracy, precision, recall, specificity, exact confusion counts and sample denominators. Type I rate is FP/(FP+TN); Type II rate is FN/(FN+TP); false alarms per warning is FP/(FP+TP), a different quantity. Undefined rates display **Not enough data**, never 0%. Small denominators are flagged. Wilson 95% intervals are descriptive; correlated storm days are not independent samples, and the intervals do not fix that dependence.

Manager agreement, goal achievement and subjective grades are separate from weather statistics. There are currently no independently verified USDA operating-action labels in the new feedback pipeline. Exact five-posture accuracy and reporting-time correctness remain unavailable. Proxy school notices never become facility-operation truth, and no closure notice never means open.

The frozen **ames-7470-v1 observation baseline**, retained **04:00 forecast benchmark**, and hourly checks remain separate. Stored historical predictions retain their original rule versions. The forecast benchmark also checks retained artifact hashes and pre-decision issuance/availability; invalid records are excluded rather than scored. Merely changing the current configuration does not recompute them or claim improved performance. The Backtesting catalog lists private `operational-feedback-v1` alongside the historical datasets without merging their labels.

## Akamai analysis

Expand **Akamai explanation & policy proposals** and explicitly request an explanation. GET requests and ordinary log browsing do not invoke inference. Durable claims prevent repeated or concurrent requests for the same statistics/provider/prompt version from calling the model twice. Interrupted requests eventually produce an audited template fallback. Configuring the provider later creates a new analysis identity.

Akamai receives deidentified aggregate metrics, fixed objective/reason categories and a bounded parameter catalog. It does not receive manager names, raw objectives, comments, contacts, decision identifiers, email addresses or credentials. Strict schemas, parameter bounds, evidence-key checks and output validation reject unsupported responses. Findings are qualitative; exact calculated figures always come from the backend. Model/provider, prompt version, input hash, validation and returned usage metadata are stored. Malformed output, timeouts, missing credentials and missing evidence return clearly labeled template explanations. Suggestions never alter the recorded decision or activate a policy.

## Policy workflow and authorization

**Analyze → save candidate → run full-engine backtest → approve → activate.** These are separate actions. Managers can also enter bounded candidates manually. Readiness and confidence brackets have their own categories; weather accuracy cannot validate their calibration or attention/deadline correctness. Without independent labels they are rejected for activation.

Only numeric parameters in existing facility-policy rules, winter-road recovery timing, readiness boundaries and evidence-confidence brackets are eligible. Official NWS rules, OPM categories, essential reporting obligations, labels, and saved snapshots stay immutable. Weather bounds are anchored to the source registry (50–150% of its original value), not repeatedly expanded with each activation. Other bounds and units are returned by `/api/policies`; recovery hours must be whole numbers and confidence brackets must remain ordered.

Default cost weights are **1 per false alarm and 5 per missed disruption**, configurable before candidate selection. These are hypothetical, unitless scenario weights, not measured injury probabilities or income losses. Loss = FP × false-alarm weight + FN × miss weight. Managers can predeclare minimum recall and maximum false-alarm rate. A Type II miss may expose workers to hazardous conditions; a Type I false alarm may disrupt tasks/income. Neither outcome is directly measured here. Zero false alarms and equal error counts are not optimization targets.

Candidates run through the actual deterministic engine on identical retained inputs, without margin-offset approximations, downloads, inference, notification sends or rewriting old results. Issuance and observation times enforce the archive’s estimated 2-hour forecast and 15-minute observation availability lags. Missing/uncertain inputs are excluded. One retained evaluation per facility/local day avoids repeated hourly examples. The pinned 7,470-day manifest and artifact hashes are verified before use.

Chronological splits are training before 2019 / validation 2019–2022 / retrospective test from 2023 for the baseline; forecasts use training before 2021 / validation 2021–2022 / retrospective test from 2023. Dates near split boundaries and storm episodes crossing boundaries are purged. Validation requires at least 30 days and five examples of each weather class. Only a candidate with lower predeclared validation loss that meets configured constraints can be approved. A locked passing candidate is evaluated once on the test partition; failed candidates never inspect test outcomes. The same proposal cannot be rerun. Previously inspected historical test dates remain retrospective, not a pristine holdout; future decisions after activation form a separately reported monitoring stream. Do not repeatedly create new candidates to optimize retrospective test scores.

Set `THRESHOLD_ADMIN_TOKEN` to a random manager-only value in the server's ignored `.env` and restart the API. Leave it empty to disable approval, activation and rollback. Enter it in the UI only for those actions. The server checks it using constant-time comparison; the browser keeps it in component memory only, not browser storage. This token supplements the deployed manager login, not a replacement for site authentication. The normal `.env.example` documents the setting without credentials.

Activation is an atomic append-only transaction. Stale proposal versions or incumbent hashes are rejected. All workers load the persisted active overlay, including after restart. Rollback restores prior configurations and appends audit events. A source-registry change marks the prior activation inapplicable and falls back to the new source registry; revalidate a new proposal. Interrupted evaluations are rejected on server restart. No threshold was activated during implementation.

## Private cloud data and recovery

SQLite remains the source of truth. The existing Akamai Object Storage sync now mirrors these private versioned objects:

- `feedback/intentions/YYYY-MM-DD/<id>.json`
- `feedback/reviews/YYYY-MM-DD/<id>.json`
- `feedback/assessments/YYYY-MM-DD/<id>.json`
- `feedback/metrics/YYYY-MM-DD/<hash>.json`
- `feedback/analyses/YYYY-MM-DD/<request-or-result-hash>.json`
- `feedback/policy-proposals`, `feedback/policy-events`, `feedback/policy-activations`
- `feedback/catalog/<metric-hash>.json` (separate operational dataset metadata)

Record objects include SHA-256 integrity hashes over the serialized object excluding the hash field. Append-only SQLite triggers protect all new records. The existing cloud marker advances after every fully uploaded row; interruptions retry safely with the same keys. Object Storage's default private objects and bucket-limited credentials remain required. The UI reports storage enabled/offline/retrying state; local work continues during outages. Existing consistent SQLite backups include the new tables and active-policy pointer and restore them on a fresh server. Operational feedback, identifying comments, contacts, local databases and secrets must never be exported to the repository dataset.

See [Akamai setup](akamai-usage.md) for private bucket configuration. No new cloud bucket or real notification provider is required. Live cloud credentials were not exercised during verification; deployment must verify the private bucket permissions, prefix isolation, sync and fresh-server restore.

## Read-only comparison utility

Run this from the repository root to compare an allowed parameter with the source registry on retained data, using a disposable database copy:

```sh
backend/.venv/bin/python scripts/evaluate_policy.py --cohort baseline \
  --parameter rules.wind.fcst_gust_advisory.value --value 35 \
  --output /tmp/closure-policy-comparison.json
```

Use `--cohort forecast` to evaluate retained pre-decision forecasts. The utility disables inference, cloud storage and notification credentials, does not activate a configuration, and writes aggregate comparisons only. It does not silently download missing datasets or rebuild the frozen manifest. See [verification](decision-grading-verification.md) for this checkout's measured results and remaining deployment checks.
