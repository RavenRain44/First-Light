# Release review — October 11, 2026

## Changes prepared locally

- Persistent weather-context banner across views, including facility, selected timestamp, year and time zone. Replay, saved decision, what-if and demo fixtures are explicitly distinguished from LIVE.
- Historical workspace tint and side borders work with both themes; text carries the distinction without relying on color. Return to live clears old evidence before fetching current weather.
- Saved weather and replay views cannot expose the operating-decision action. Production API rejects non-live operating decisions. Existing isolated demo API workflows remain supported.
- Notification pages no longer crash on plain HTTP: UUID idempotency keys use a secure getRandomValues fallback when randomUUID is unavailable. Shared location and decision fields have explicit accessible names.
- AI polling now stops after repeated transport failures rather than polling indefinitely; a previous successful brief is preserved.
- Production Compose forces DEMO_MODE=false. New deployment setup defaults to manager authentication and protects all API routes, including reads of contacts and decision records. Existing authentication files are not silently changed.

## Verified locally

- Backend: 259 tests pass. Isolated databases, mocked inference/providers and disabled cloud credentials were used.
- Frontend: 46 unit tests pass; production build passes.
- Browser: 14 isolated workflow tests pass. Notification coverage checks four groups, editable shared text, unselected recipients, review error feedback and simulated dispatch; APIs are mocked, with backend behavior verified separately.
- Browser replay checks cover curated events, arbitrary dates/minutes, normal-weather control, missing archive failures/retry, timeline/playback consistency, weather-specific graphs, pending response cancellation, mobile/dark context labeling and saved-decision-to-live transitions.
- Notification backend tests cover deterministic routing, essential/telework/detail/travel personnel, time-zone schedules and fallback, four-group restoration, draft edits, approval invalidation, one-action dispatch, retries, delays, duplicate prevention, restart persistence, superseded decisions, audit history and separate test contacts.
- AI tests cover manager agreement/override reasoning, all scenarios, template fallback, immutable snapshots and exclusion of contact details from prompts.
- Camera tests cover saved frames, multiple views, immutable capture, interrupted capture and restart behavior. Charts derive from the recorded snapshot. No live camera or road evidence is substituted for missing historical reconstruction inputs.
- Backtesting tests cover frozen cohort identity, evidence qualification, error rates, sensitivity comparisons and integrity-checked storage/restore. The 7,470-day cohort represents weather disruptions, not 7,470 confirmed office closures.
- API validation, append-only decision records and useful error states have automated coverage.
- Deployment shell syntax and Git whitespace checks pass. .env is untracked; Docker build context excludes credentials, private contacts and the local database.

## Still required before public release

1. Container and staging deployment smoke test: Docker is not installed in this environment, so image build, container health, HTTPS, Caddy authentication and volume persistence were not executed. Run these on the deployment host.
2. Existing servers: review deploy/manager-auth. Earlier setup could leave authentication disabled or protect only writes. Apply authenticated access to /api/*, validate Caddy and reload. Verify unauthenticated requests cannot read notification contacts or make decisions. Restrict host/API access to prevent bypassing Caddy.
3. Populate the frozen dataset in the persistent production volume using the repository restore command. Image contents alone do not guarantee a named volume contains the dataset. Validate its count and metrics before advertising backtesting availability.
4. Verify actual weather/provider integrations and timeouts on staging. Tests mock network failures and providers; no paid inference or real email/SMS was invoked. Confirm the intended provider credentials without exposing them in browser code.
5. Only after explicit authorization, run one real notification to an allowlisted test contact. SMTP acceptance is not confirmed inbox or SMS delivery. Synthetic employee deliveries remain simulated.
6. A complete accessibility audit and human usability check remain necessary. Browser tests cover mobile and dark rendering and semantic controls, but do not certify screen-reader usability or all contrast ratios.

Local checks support a staging release. Public production readiness depends on these environment-specific checks; no deployment, push or merge was performed in this review.

## UI improvements to prioritize next

- High priority, small effort: show a compact “selected groups / immediate / scheduled” confirmation next to Approve and alert, with facility-local scheduled times. The existing composer and send totals already provide the underlying information.
- High priority, medium effort: put a simple connection-status view behind a manager-only settings link instead of exposing SMTP implementation details in the main workflow.
- Medium priority, small effort: move Replay from More tools into a direct navigation action if historical analysis is a frequent task.
- Medium priority, medium effort: lazy-load maps, video and technical analysis panels. The production build still reports large JavaScript chunks; this affects initial loading on slow connections.
- Medium priority, medium effort: perform timed task testing with managers (record, edit, select, send) and a screen-reader/keyboard review before further visual redesign.

## Deployment and rollback

Deploy only after review and authorization. On the deployment host:

1. Record the currently running Git revision and image ID. Back up the SQLite database with SQLite's backup API and preserve the existing named volume. Do not copy an actively written database as the only backup.
2. Configure SITE_ADDRESS, private local contacts, manager authentication and intended provider settings. Keep secrets outside Git. DEMO_MODE is forced false by production Compose.
3. Run bash -n deploy/scripts/setup-linode.sh. Validate Caddy with the host's SITE_ADDRESS and manager-auth mount. Build with docker compose -f deploy/compose.prod.yaml build.
4. Start with docker compose -f deploy/compose.prod.yaml up -d. Check /api/health through authenticated HTTPS and on the host's loopback port. Verify container health and inspect logs without publishing secrets.
5. For repository data, run docker compose -f deploy/compose.prod.yaml exec app python -m scripts.dataset_repo restore. It verifies checksums and refuses conflicting local records; do not delete production data to bypass a conflict.
6. Verify Today, replay, saved decisions/charts/cameras, simulated notification edits/group selection/send, and restart persistence on staging. Confirm production SMTP tests remain separate, explicit actions.

Rollback: redeploy the recorded previous image/revision with the same persistent volume. Never use docker compose down -v. If a schema change is incompatible with the older image, stop the app and restore the pre-deployment database backup before restarting. This review changes no database schema. Retest health, authentication and saved records after rollback.
