# Closure Call competition review

Reviewed October 11, 2026, against commit `025b1c6`.

## Assessment

Closure Call is a strong fit for the USDA challenge and has substantive Akamai integration. Its most persuasive feature is the complete connection between recorded weather, a human operating decision, targeted communications and later evidence review. The code supports a credible demonstration. Cloud deployment, current external-service availability and competition eligibility still need confirmation; passing local tests does not establish those facts.

Authority: the [published Hack Midwest challenge descriptions and rules](https://hackmidwest.com/), with the supplied brief in `docs/closure-call-challenge.txt`. `PROJECT_PLAN.md` describes team intentions, not additional competition requirements. This review distinguishes implemented features, earlier recorded verification and currently unverified deployment behavior. It adds no product changes and sends no notifications.

## USDA deliverables

### 1. Working system and real weather — implemented; live demonstration needed

`backend/adapters/nws.py` ingests NWS alerts and forecasts. Iowa observations, roads, pavement sensors and outlooks supply supplementary evidence. The synthetic Ames facility and 270-person roster include schedules, dated details, telework, emergency-required personnel and accessibility fields. Winter/ice, wind/convective weather and cold form a focused scope.

The nationwide Live Check in `backend/app/routers/livecheck.py` retrieves active NWS alerts even in demo mode and evaluates a clearly identified hypothetical facility. This provides a practical demonstration when Ames has no active warning. Iowa-only supplementary inputs are unavailable outside Iowa and confidence is reduced. Do not describe that relocated result as an actual USDA operating decision.

Before judging, demonstrate a newly fetched, supported active alert with its source timestamp. Then return to Ames for the real manager workflow. Cached demo weather, replay and live weather now have distinct labels, but an offline replay alone does not demonstrate current ingestion.

### 2. Recommendation and reasoning — implemented

The deterministic engine supplies five operating postures, timing, triggered rules and margins, evidence provenance, confidence factors and counterfactuals. `AIPanel.tsx`, `ThreatPanel.tsx` and the dashboard expose the explanation and supporting evidence. Akamai drafts prose; it does not choose the posture or recipients. Templates and explicit insufficient/provisional-evidence states preserve operation during failures.

The numeric confidence score measures weighted evidence quality. It is not a calibrated probability that a closure is correct. Cooper readiness is a separate local policy, not a USDA/NWS standard. Keep both distinctions explicit in the pitch.

### 3. Notification package — implemented with content gaps

`backend/app/notifications.py` resolves effective assignments, schedules, leave, essential status and telework into four visible groups. Managers select recipients, edit shared location/decision wording and group instructions, review timing and approve dispatch. Approval invalidates on edits; scheduled simulation, duplicate prevention, retries, cancellation and audit events are persisted. Remote/travel/detail awareness uses employee work-start time with configurable fallback, rather than a universal morning hour.

Employee delivery remains simulated. `real_delivery.py` provides a separate, explicit SMTP/email-to-SMS gateway test path restricted to local test contacts. It labels messages as tests and distinguishes SMTP acceptance from confirmed inbox or phone delivery. Do not present that path as production roster delivery or guaranteed SMS receipt.

Two content limitations matter for the core workflow:

- `message_text()` returns only the three editable boxes when `location_text` exists. That branch omits the package's `next_update` guidance. A read-only synthetic rendering confirmed the omission.
- Delay and early-dismissal templates explicitly say no specific arrival/departure time was recorded. `DecisionIn` has no structured field for those times. Managers can type the time into instructions, but the system does not ensure it is present or consistently represented across groups.

A concise footer for next-update/contact guidance and authoritative facility-local reporting-time fields would address these gaps while preserving the simple composer. Essential reporting stays in force, but default wording is generic supervisor guidance rather than role-specific reporting instructions. Accessibility needs are retained as follow-up flags; the four-group composer is not a fully adapted-message system for every need.

### 4. Decision record — implemented; describe integrity precisely

Snapshots retain normalized inputs, source timestamps, evaluated rules, thresholds version/hash, confidence, recommendation and the manager decision link. SQLite triggers prevent ordinary updates/deletes to snapshots and decisions; AI interpretations and notification audit events are appended separately. The decision log reconstructs the saved weather context. Historical chart thresholds now use recorded values. Saved camera frames are served from retained bytes, with missing capture explicitly unavailable.

This is content-hashed snapshot evidence with append-only database protections. It is not the hash-chained decision ledger proposed in `PROJECT_PLAN.md`: the models contain no `prev_hash`, and `scripts/verify_chain.py` is empty. Do not claim chain verification or resistance to a privileged database administrator rewriting both data and hashes. Hash chaining is a plan enhancement, not necessary to claim the implemented reconstructable record.

Traffic-camera capture is asynchronous after recording. Traffic-frame metadata correctly uses retrieval time, while archived camera images retain source-frame time. Describe those pictures as frames captured around decision recording, not proof of an exact instant across every camera.

### 5. Threshold defensibility — partial; clearly disclose policy assumptions

The YAML registry contains 36 rules: 23 marked official and 13 policy. Nineteen have `verified: true`; seventeen have `verified: false`. These are registry declarations, not a new independent verification of the cited sources. The UI exposes anchors, source links, margins and unverified badges.

Unverified rules include the six-inch/12-hour snow criterion, several road/RWIS and observed-ice thresholds, the 1.5-inch forecast snow policy, convective watch/SPC categories and cold cutoffs. The source-backed weather criterion and its mapping to workplace action are different decisions; an official warning definition does not make the application's closure policy USDA-approved.

Use the Thresholds tab as the working defensibility exhibit. `scripts/gen_thresholds_doc.py` is empty and no generated `THRESHOLDS.md` exists, so the plan's documentation pipeline is unfinished. Prioritize verification of the rules used in the demonstration and state which remaining choices need local safety/continuity approval.

## Akamai judging criteria

- **Impact & usefulness: strong.** The manager workflow addresses scattered evidence, early-morning decision pressure, changed reporting instructions and reconstruction afterward. Demonstrate a practical result with a timed workflow; do not invent hours saved or avoided injuries.
- **Powered by Akamai: implemented integration; deployment proof pending.** Backend-only workshop inference, bounded/schema-validated drafting and audit metadata are substantive uses. Object Storage code mirrors snapshots, interpretations, decisions, notifications, charts, cameras and backups. Linode/Docker/Caddy deployment files exist. Earlier successful workshop requests are documented in `docs/akamai-usage.md`; they do not prove today's availability or a running Akamai VM. Show the deployed URL, accepted Akamai provider identity and an actual successful bucket sync/restore. PostgreSQL, pgvector, Valkey and LKE are not needed simply to make the resource list longer.
- **Technical execution: strong local evidence; release verification incomplete.** The immediately preceding merged validation passed 295 backend tests, 51 frontend tests, 18 browser tests and the production frontend build. Browser API responses were mocked. This review did not rerun those unchanged checks. The local API health check returned `ok: true`, live weather mode and enabled Akamai configuration. This is a health/configuration result, not a new accepted inference request or proof of remote deployment. No deployment hostname was configured in the local `.env`. `.github/workflows/ci.yml` and `deploy.yml` are both empty: do not claim automated green CI or automatic deployment. The release checklist still calls for host/container/HTTPS/authentication/persistence checks. Large frontend chunks remain a performance concern.
- **Creativity & innovation: strong.** Emphasize evidence time travel, archived camera angles, deterministic counterfactuals, audience-specific notification timing and grounded AI wording. These demonstrate a workflow beyond a chat interface. Backtesting is valuable supporting evidence but should not displace the operational demo.

## Competition and plan discrepancies

The published rules specify a three-minute prototype pitch, no slides, one project, one-to-five onsite participants, fresh competition-period assets and a development freeze. The website lists submission at 08:00 Sunday October 11. Confirm any organizer updates and the applicable cutoff before changing the competition build. The page describes both a 24-hour period and scheduled times; the organizer's announced cutoff should resolve any ambiguity.

The README lists five builders, consistent with the size limit; onsite attendance and registration are not established by source code. The earliest visible commit is dated October 10 at 09:48 Central, consistent with the published kickoff date, but Git history alone cannot certify when assets were created. Preserve actual provenance; do not rewrite timestamps to imply eligibility.

`PROJECT_PLAN.md` conflicts with the pitch format by proposing about five minutes and an architecture slide. It also proposes 24–32-hour polish work, which cannot be assumed available in this competition. Its acknowledgments, flood/gauge scope, six locations, Managed PostgreSQL/pgvector, Valkey, embeddings, extraction agent and hash chain exceed or differ from the present product. These are original ambitions, not failures to satisfy sponsor requirements. The current focused Iowa design, SQLite storage and deferred acknowledgments are reasonable scope choices.

The plan's claims should be revised to distinguish shipped behavior and future work. `docs/demo-script.md`, `architecture.md`, `verification-log.md` and `costs-and-teardown.md` are empty. Some relevant content exists in the README and Akamai usage document, but those placeholders should not be cited as completed deliverables. The footer identifies the challenge and synthetic facility; it does not contain the plan's explicit statement that the prototype is not an official USDA or OPM system.

## Backtesting claims to use carefully

The frozen 7,470-day observation baseline is a weather-disruption benchmark, not 7,470 confirmed office operating decisions. Earlier documentation reports 96.64% ordinary agreement, 72.05% balanced accuracy and 44.10% disruption recall for that retained cohort. None is closure-decision accuracy. School/university proxy notices do not establish USDA operations. Confidence categories and Wilson intervals do not establish a 95% probability that an office was open or closed.

Newer repository-dataset documentation describes a default 1,884-day forecast cohort for 2019–2026, while older portions of `historical-backtesting.md` still describe only a small forecast sample. Frozen old results are useful, but they should be labeled as retained baseline results rather than current-rule/default-dataset performance. Similarly, the signed-margin cost experiment is retrospective sensitivity analysis, not a trained AI injury predictor. Cost ratios are assumptions; neither injury risk nor lost income was measured from these records.

In the pitch, identify the dataset, decision cutoff, label definition, false-alarm/miss counts and forecast availability alongside any result. Avoid a headline such as "96% accurate at closing USDA offices" or "AI trained to prevent injury." No metric refresh was run during this review.

## Priority actions

1. **Establish eligibility and freeze the judged revision.** Confirm submission/attendance and organizer timing. After cutoff, keep recommendations in this review separate from the submitted product unless organizers explicitly permit changes.
2. **Prove the running Akamai deployment.** Verify HTTPS/manager access, fresh NWS ingestion, accepted Akamai inference, Object Storage persistence and restart/restore using the deployed host. Keep screenshots of resource/provider evidence free of credentials and contact details.
3. **Close notification-content gaps when changes are permitted.** Preserve next-update/contact guidance; make delay/departure times explicit and consistent. Keep normal roster delivery labeled simulated.
4. **Align the presentation with reality.** Use a three-minute app-only demonstration; remove claims about unbuilt infrastructure, hash chains and actual closure accuracy. Explain verified versus assumed thresholds.
5. **Complete supporting documentation and CI when permitted.** Replace empty placeholders with accurate content and implement actual checks before claiming automation. Public-release authentication, persistence and accessibility work remain separate from hackathon feature coverage.

## Suggested three-minute app demonstration

- **0:00–0:20:** Explain the manager's early-morning problem and name both sponsor challenges.
- **0:20–0:45:** Show fresh nationwide NWS Live Check evidence; identify the hypothetical location and return to Ames.
- **0:45–1:10:** Show a posture, the rule/source/margin behind it and what would change it. Label replay if using a retained storm.
- **1:10–1:35:** Show the manager decision and reasoning using a legitimate live or cached-demo decision context. Production replay/what-if views intentionally cannot record operating decisions.
- **1:35–2:10:** Show shared message wording, the four audiences, essential instructions and remote scheduling; demonstrate simulated approval/dispatch. Avoid live test contacts during the public pitch.
- **2:10–2:40:** Open that decision's saved weather, recorded chart threshold and camera frames or honest unavailable status.
- **2:40–3:00:** Show accepted Akamai inference/provider evidence and actual Cloud copy status, if verified. Finish on the human decision and reconstructable record.

Preload a historical example and an existing decision record as clearly labeled backups. Sign in before the demo and avoid waiting for a long inference request. Test the planned sequence on the judged build without mutating its code after the cutoff.
