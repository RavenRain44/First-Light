# FirstLight — Storm Closure Decision Support (USDA × Akamai)

> Working name. Rename freely. Tagline: *"The decision is still human. Everything else is ready before they wake up."*

## 0. How to use this file

Drop this in the repo root as `PROJECT_PLAN.md`. Paste the "Mission" and "Non-negotiable principles" sections as the first prompt to your coding agent (or reference this file from `CLAUDE.md` / `AGENTS.md`). Anything tagged **[VERIFY]** is from memory or a secondary source. Check it against the primary source in the first hour and record the result in `docs/verification-log.md`.

---

## 1. Mission

Build a working, deployed, AI-assisted decision-support system that:

1. Ingests **live National Weather Service (NWS) data** plus at least one supplementary signal.
2. Evaluates threat against a **synthetic USDA facility**.
3. Recommends a **graded closure posture** (not a binary) to a **human decision-maker**.
4. Produces the **notification package** that reaches the right employees, with the logic for who is and isn't included.
5. Writes a **tamper-evident decision record** that can reconstruct what was known, when, and what was decided.
6. Runs on **Akamai Cloud (Linode)** and uses **Akamai-hosted AI inference** in ways that go well beyond a chatbot.

One project, two submissions:

| Challenge | What they want | How we satisfy it |
|---|---|---|
| **USDA (actionable)** | Real NWS data, graded recommendation with reasoning, notification package, decision record, defensible thresholds | Sections 7–11 |
| **Akamai (cloud)** | Real problem, uses Akamai resources and inference, solid technical execution, creative | Sections 5, 12 |

### Judging-criteria crosswalk (keep this table honest; it becomes the README's "Why we win" section)

| Criterion | Our evidence |
|---|---|
| Impact & usefulness | Federal facility closure decisions are made at 4am from scattered inputs. We put inputs, thresholds, roster logic and audit trail in one place. |
| Powered by Akamai | Linode compute, Managed PostgreSQL (+ pgvector), Object Storage (evidence archive), Valkey (cache/queue/rate limit), Akamai-hosted inference (extraction, grounded drafting, tool-calling analyst, embeddings). Stretch: LKE. |
| Technical execution | Pure deterministic engine, golden-fixture tests, CI/CD, live deploy, graceful degradation when inference or NWS is down. |
| Creativity | Counterfactual "what would change this recommendation" engine, hash-chained decision record with time-travel, and an LLM that is *never allowed to decide*. |

---

## 2. Non-negotiable principles

1. **Humans decide.** The system recommends. A person approves, modifies or overrides, and an override requires a reason. Nothing is sent to employees without human approval.
2. **The engine is deterministic; the LLM never picks the posture.** Posture, thresholds, confidence and recipient lists come from pure, testable code. The LLM only (a) extracts structure from messy text, (b) drafts prose from the engine's structured output, (c) answers "why / what if" by calling the engine as a tool.
3. **Every claim is traceable.** Each input carries source, URL, `issued_at`, `fetched_at`, payload hash, and a pointer to the archived raw payload. If we cannot cite it, we do not show it.
4. **Real data in the demo.** Live NWS API, live alerts somewhere in the US. Replay fixtures exist only for tests and as a clearly labeled fallback.
5. **Depth over breadth.** One facility profile, three hazard types, handled well.
6. **Time is injectable.** `evaluate(facility, evidence, now)` takes `now` as an argument. That gives time-travel, backtests, sensitivity analysis and reproducible tests.
7. **Synthetic people only.** No real PII, no real phone numbers (use 555-01xx), and no real messages sent to anyone except opted-in teammates behind a feature flag.
8. **Say what it is.** Footer on every screen: *"Prototype for HackMidwest. Not an official USDA or OPM system."*
9. **Fail visibly.** Stale or missing data lowers confidence and is displayed. It never silently falls back.

---

## 3. Scope

**In:**
- One facility profile instantiated in several places.
- Three hazards: **winter weather (ice/snow/cold)**, **flooding**, **severe convective wind/tornado**.
- NWS as the core source plus USGS river gauges as the supplementary signal.
- Postures: normal / open with option for unscheduled leave or telework / delayed arrival / early dismissal / closed.
- Notification package, decision record, threshold defensibility doc.

**Out:**
- Other facility types, other hazards (wildfire smoke, heat), real SMS/voice delivery, auth/SSO beyond a simple role switch, mobile app.

**Stretch (only after the core is green and deployed):**
- State DOT / 511 road conditions.
- OPM current-status cross-check for the DC HQ facility.
- Backtest harness on historical events.
- LKE deployment.
- Go ingest service (see Section 6).

---

## 4. Architecture

```
        NWS API (alerts, points, gridpoints, obs)      USGS / NWPS gauges     [stretch: 511, OPM status]
                      │                                        │
                      ▼                                        ▼
              ┌──────────────── Ingestors (scheduled, polite, cached) ────────────────┐
              │  raw payload → Object Storage (sha256)  │  parsed → Postgres          │
              │  response cache + rate limits → Valkey                                │
              └───────────────────────────────┬──────────────────────────────────────┘
                                              ▼
                                  Evidence Bundle (as-of time T)
                                              ▼
   Facility + Roster (synthetic) ─▶  DECISION ENGINE (pure, deterministic)
   Threshold Registry (YAML+cites) ─▶  posture · thresholds crossed + margin · confidence · counterfactuals
                                              ▼
                     ┌────────────────────────┴───────────────────────┐
                     ▼                                                ▼
          Recipient Resolver (explainable)                   LLM layer (Akamai inference)
          audience variants · channel routing                extraction · grounded drafts · analyst agent · embeddings
                     └────────────────────────┬───────────────────────┘
                                              ▼
                        Human decision (approve / modify / override + reason)
                                              ▼
                     Notification simulator + ack tracking   +   Decision Record (hash-chained, Postgres + Object Storage)
                                              ▼
                                 Web UI (map, decision view, record, thresholds)
```

### Akamai resource mapping

| Need | Akamai service | Notes |
|---|---|---|
| App runtime | Linode instance + Docker Compose (MVP); LKE (stretch) | Deploy a hello-world on day one. |
| Records, roster, vectors | Managed PostgreSQL (+ pgvector) | Decision record, evidence index, precedent search. |
| Evidence archive, exports | Object Storage (S3-compatible) | Raw NWS/USGS payloads by hash; nightly JSONL export of the decision chain. |
| Cache, rate limits, job queue | Valkey | NWS ETag/Last-Modified cache; per-user LLM rate limit. |
| AI | Hosted inference endpoint (team key from organizers at kickoff) | Wrap in an `LLMClient` interface. Endpoint, model names and credentials arrive at kickoff, so keep them in env vars. |

**Read first (starter kit):** `github.com/akamai-developers/akamai-workshop-hackmidwest`. Start with `docs/00_prework.md`, `docs/inference.md`, `notebooks/README.md`, `docs/03_body.md` (Linode), `docs/02_memory.md` (Postgres), `docs/01_knowledge.md` (Object Storage), `docs/05_valkey.md`, and **`docs/costs.md` before provisioning anything billable**. The kit is Python (`agent/`, `Dockerfile`, `compose.yaml`, `k8s/`, `deploy/`), so we reuse its inference client and deploy scripts.

---

## 5. Stack

Chosen for speed on Akamai's Python starter kit while giving the team new tools to say they've used.

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + psycopg, APScheduler (or a small worker process), `httpx` with retry/backoff.
- **Frontend:** React + TypeScript + Vite, Tailwind, Leaflet or MapLibre for the map. *Fallback if frontend capacity is thin:* FastAPI + Jinja + HTMX.
- **Data:** Managed PostgreSQL (+ pgvector), Valkey, Object Storage (boto3 against the S3-compatible endpoint).
- **DevOps:** Docker, Compose, GitHub Actions (lint, type-check, tests, build, push to GHCR, deploy to Linode over SSH), `gitleaks` secret scan, Dependabot.
- **Quality:** pytest, hypothesis (property tests), ruff, mypy, Playwright smoke test (stretch).

---

## 6. Data sources

### 6.1 NWS (core). No key, but a descriptive `User-Agent` is required.

```bash
UA='User-Agent: firstlight-hackmidwest (team-contact@example.com)'

# Active alerts by state, or by facility point
curl -H "$UA" -H "Accept: application/geo+json" "https://api.weather.gov/alerts/active?status=actual&area=IA"
curl -H "$UA" -H "Accept: application/geo+json" "https://api.weather.gov/alerts/active?point=41.59,-93.62"

# Resolve a point → forecast grid, zones, observation stations
curl -H "$UA" "https://api.weather.gov/points/41.59,-93.62"
# then follow properties.forecastGridData (raw numerical grid), forecastHourly, observationStations
```

Etiquette: send the User-Agent, honor cache headers and ETags, back off on 429/5xx, cache in Valkey, and archive every raw response.

**Alert fields to use:** `event`, `severity`, `certainty`, `urgency`, `response`, `onset`, `ends`, `expires`, `effective`, `sent`, `messageType`, `headline`, `description`, `instruction`, `areaDesc`, `geocode.UGC`, `parameters` (VTEC, `maxWindGust`, `maxHailSize`, `tornadoDetection`, etc.).
**Gridpoint fields to use:** `iceAccumulation`, `snowfallAmount`, `windGust`, `windSpeed`, `windChill`, `temperature`, `probabilityOfPrecipitation`, with `validTime` intervals (`start/PT3H`). **[VERIFY]** field availability for each WFO.
**Gotcha:** many alerts have `geometry: null` and only list zones. Use `?point=` and UGC matching rather than polygon-only logic.

### 6.2 Supplementary signal (required): river gauges for the flood hazard
- **NWS NWPS** (`api.water.noaa.gov/nwps/v1/gauges/...`): observed and forecast stage with flood categories (action / minor / moderate / major). **[VERIFY]** endpoint shapes.
- **USGS** gauge height (parameter 00065). **[VERIFY]** whether the legacy `waterservices.usgs.gov` endpoints still work or have moved to the newer USGS Water Data APIs.
- Each facility has a synthetic `nearest_gauge` and `flood_exposure` attribute.

### 6.3 Stretch signals
- State DOT / 511 road conditions: pick **one** state with an open feed and confirm it in hour 0. WZDx is a standard feed format for work zones.
- OPM current operating status for the DC HQ facility, shown as a cross-check against our recommendation. Scraping is fragile, so treat it as optional.
- Local government / school closure announcements via LLM extraction. It is a cool demo but unreliable, so it comes last.

### 6.4 Optional breadth module (Go)
If someone wants Go, the NWS/USGS poller can be a standalone service that writes to `raw_observations` and Object Storage. The contract is the DB schema, so the language is swappable. **Do not start it until the Python pipeline works end to end.**

---

## 7. Facility and roster model (synthetic)

**Facility profile (the one profile):** "USDA Service Center" with FSA, NRCS and RD co-located, about 60 employees.

Fields: `id`, `name`, `lat`, `lon`, `tz` (IANA), `ugc_zones`, `nearest_gauge`, `flood_exposure`, `hours` (open/close local), `after_hours_contact`, `region`.

**Instantiate in about six places** to show variety: Iowa (ice), Gulf Coast (hurricane/flood), Mississippi Delta (flood), Plains (tornado/wind), Mountain West, Southwest. Add a **"Teleport facility"** control that clones the profile to the centroid of any currently active qualifying NWS alert. That is how the live demo always has real severe weather.

**Employee fields:** `id`, `name`, `role`, `home_facility_id`, `status_today` (`on_site | telework | on_detail(facility_id) | leave`), `essential` (emergency employee flag), `telework_eligible`, `telework_agreement_signed`, `accessibility_needs[]` (mobility, hearing, vision, evacuation assistance), `shift_start`, `commute_minutes`, `commute_origin_zone`, `preferred_channels[]` (priority order), `language`, `supervisor_id`, `contact` (fake).

Generate with a seeded script (`scripts/seed.py`, fixed RNG seed) so every demo is reproducible. Include deliberate edge cases: someone on detail to another site, someone on leave, three essential staff, someone with hearing needs and no voice channel, someone whose home zone is under a different alert.

---

## 8. Decision engine (`engine/`, pure Python, no I/O)

### 8.1 Interface
```python
evaluate(facility: Facility, evidence: EvidenceBundle, now: datetime, registry: ThresholdRegistry) -> Recommendation
```

### 8.2 Output (JSON, also rendered in the UI)
```json
{
  "facility_id": "...", "as_of": "2026-10-10T09:07:00Z", "engine_version": "git:abc123", "registry_version": "git:def456",
  "posture": "DELAYED_ARRIVAL",
  "delay_hours": 2,
  "shelter_now": false,
  "decision_deadline": "2026-10-10T09:30:00Z",
  "inputs": [{"id": "...", "source": "NWS alerts", "url": "...", "issued_at": "...", "fetched_at": "...", "sha256": "...", "fields_used": {}}],
  "thresholds_crossed": [{"id": "ice_accum_ge_0.25in", "observed": 0.31, "limit": 0.25, "margin": "+0.06 in", "posture_floor": "CLOSED", "rationale_ref": "THRESHOLDS.md#ice"}],
  "confidence": {"level": "MEDIUM", "components": {"alert_certainty": "Likely", "lead_time_h": 5, "source_agreement": "2 of 2", "freshness": "OK"}},
  "what_would_change": [{"if": "ice accumulation forecast < 0.10 in", "then": "TELEWORK_OPTION"}, {"if": "onset moves before 06:00 local", "then": "CLOSED"}],
  "rationale_template": "...", "rationale_llm": "...", "rationale_grounded": true
}
```

### 8.3 Posture ladder (anchored to OPM operating-status categories)
OPM's DC-area categories: **Open · Open with option for unscheduled leave/telework · Open with delayed arrival (with that option) · Early departure (immediate or staggered) · Closed**. In a closure, emergency employees report, and telework-agreement employees follow their agreement and agency policy. **[VERIFY]** the current wording in OPM's *Governmentwide Dismissal and Closure Procedures* handbook. Outside DC, agencies decide locally and are encouraged to follow these procedures.

`NORMAL < TELEWORK_OPTION < DELAYED_ARRIVAL / EARLY_DISMISSAL < CLOSED`, plus an **overlay flag `SHELTER_NOW`**. Delay and early dismissal are not strictly ordered. Which one applies depends on *when* the hazard hits.

### 8.4 Timing logic (the key idea)
Posture is a function of **severity level over time**, not a single number.

1. For each hazard, build an hourly severity timeline for the next 24h from alerts (onset/ends/expires) and gridpoint values. Levels: **0 none, 1 elevated, 2 advisory-level, 3 warning-level, 4 extreme**.
2. Define windows from facility hours and roster commute data: **arrival window** (about shift start minus longest commute minus buffer, to shift start plus 30 min) and **departure window** (close minus lead time, to close plus 90 min).
3. Starting decision table (every value is a hypothesis to defend, tune and cite):

| Condition | Posture |
|---|---|
| Max level ≤ 1 across both windows | NORMAL |
| Level 2 in either window, nothing ≥ 3 | TELEWORK_OPTION |
| Level ≥ 3 in arrival window, clears by midday | DELAYED_ARRIVAL (hours = clear time − start, rounded up, capped by policy) |
| Level ≥ 3 begins mid-day, before or in departure window | EARLY_DISMISSAL (depart-by = onset − commute lead − buffer) |
| Level ≥ 3 across arrival window **and** persists past midday, or level 4 anywhere in the workday | CLOSED |
| Tornado Warning, Flash Flood Emergency or similar imminent life-safety alert covering the site | `SHELTER_NOW` overlay (pre-approved template, one-tap confirm; whether this may auto-send is an agency policy question, so flag it in the docs) |

### 8.5 Threshold registry (`engine/thresholds.yaml`)
Every threshold has: `id`, `hazard`, `metric`, `value`, `unit`, `level_or_floor`, `source_type` (**nws_definition | opm_category | state_dot | agency_policy_assumption**), `source_url`, `quote_or_summary`, `retrieved_at`, `verified_by`, `notes`.

Starting anchors (all **[VERIFY]**; NWS criteria vary by forecast office):
- **Alert tier:** Warning → level 3, Watch → level 2 (timing-dependent), Advisory → level 2 or 1. `severity` / `certainty` / `urgency` modulate confidence and timing, not the base level.
- **Ice:** ≥ 0.10 in → level 2; ≥ 0.25 in → level 3 (commonly cited Ice Storm Warning criterion); ≥ 0.50 in → level 4.
- **Wind:** sustained ≥ 31 mph or gusts ≥ 46 mph → level 2 (Wind Advisory baseline); sustained ≥ 40 mph or gusts ≥ 58 mph → level 3 (High Wind Warning baseline).
- **Severe thunderstorm:** gusts ≥ 58 mph or hail ≥ 1 in (NWS "severe" definition).
- **Wind chill:** use the local WFO's advisory/warning criteria, since they vary a lot by region.
- **Flood stage:** action → 1, minor → 2, moderate → 3, major → 4, scaled by the facility's `flood_exposure`.

**Anything tagged `agency_policy_assumption` must be listed in `THRESHOLDS.md` as requiring sign-off from a USDA safety or continuity official.** Say so plainly in the docs. That is honest, and judges will respect it.

### 8.6 Confidence
Categorical **HIGH / MEDIUM / LOW**, with an explicit rule table over: alert `certainty`, lead time to onset, agreement between alert and gridpoint forecast, supplementary-signal corroboration, and data freshness. Avoid fake-precision percentages, and always show the components.

### 8.7 "What would change the recommendation" (counterfactual search)
Perturb each input and re-run `evaluate`. Report the smallest change that flips the posture up or down ("if the ice forecast drops below 0.10 in → telework option"). This is cheap because the engine is pure, and it is a standout feature.

### 8.8 Threshold defensibility deliverable
- `scripts/gen_thresholds_doc.py` generates `THRESHOLDS.md` from the YAML (source, quote, retrieved date, verifier).
- **Sensitivity plots:** sweep each key threshold and show where posture flips.
- **Backtest (stretch):** replay 3–5 known events through the engine with `now` injected. The Iowa Environmental Mesonet archive is a likely source for historical warnings **[VERIFY]**. Report, honestly, where the engine would have disagreed with what happened.

---

## 9. Notification package

### 9.1 Recipient resolution (explainable)
Evaluate rules in order, and store **an inclusion/exclusion reason for every employee in the roster**, including the ones left out:

1. Home facility = this facility and scheduled today → candidate.
2. `on_detail(other)` → exclude from this notice and flag "check posture at {other facility}". Optionally FYI to the supervisor.
3. `leave` → exclude, supervisor digest only.
4. `telework` today → FYI variant, no action required (config: suppress overnight).
5. `essential = true` → **essential-personnel variant**: reporting requirements unchanged, plus safety guidance.
6. `telework_eligible` and agreement signed → under closure/delay, "work remotely per your agreement" variant. **[VERIFY]** against agency policy.
7. `accessibility_needs` → adjust **channel and format**. Voice or TTY-friendly path, plain-text email, no reliance on color or emoji. Evacuation-assistance staff on early dismissal or shelter also notify their buddy or supervisor.
8. Everyone else on site → standard variant.

### 9.2 Variants and content checklist
Variants: standard on-site · essential · telework-eligible · already teleworking (FYI) · accessibility-adapted · supervisor digest · (stretch) visitors/contractors.
Every message must contain: **what is happening · whether it applies to *you* · what to do · by when / until when · who to contact**. SMS ≤ 320 characters; email longer. Automated checker enforces this.

### 9.3 Timing and routing
- **Send time** = `max(now, earliest_departure − buffer)`, where `earliest_departure = shift_start − commute_minutes − prep`. The UI shows a countdown ("last moment this can still change anyone's morning: 05:20").
- **Urgency tiers:** *Immediate* (SMS + push + voice, wakes people), *Time-sensitive* (SMS + push), *Informational* (email at a sensible hour).
- **Escalation:** no acknowledgment in N minutes → voice call → supervisor. Acknowledge by replying `1`.
- `ChannelAdapter` interface (SMS / push / email / voice / Teams) with **simulator adapters** that write to an outbox table and render a phone-style preview. Real sending is feature-flagged and limited to opted-in teammates.

---

## 10. Decision record (the deliverable agencies care about most)

Append-only Postgres table `decision_records`. Each row includes:
- `id`, `facility_id`, `created_at`, `prev_hash`, `hash = sha256(canonical_json(row) + prev_hash)` (tamper-evident chain)
- `evidence_snapshot` (ids and hashes of every input, with `issued_at` and `fetched_at`) and the Object Storage keys of the raw payloads
- `engine_version`, `registry_version`, full `recommendation` JSON
- LLM calls: model, parameters, prompt, output, grounding-check result
- Human action: `approved | modified | overridden`, actor, **reason (required on override)**, timestamp
- Notification package (recipients with reasons, messages, routing) and delivery/ack events
- **Bitemporal fields:** `observed_at` (when the world said it) vs `fetched_at` (when we knew it)

Features:
- **Time-travel view:** "Show me exactly what the manager could see at 03:58."
- Chain verification endpoint and a UI badge ("chain intact, N records").
- Nightly JSONL export to Object Storage.
- Recommendation re-computed from stored evidence must **match the stored recommendation** (reproducibility test).

---

## 11. LLM layer (Akamai-hosted inference)

Build behind `LLMClient` with a deterministic template fallback for each use. If inference is down, the app still works, and the UI says "AI drafting unavailable, using templates."

| # | Use | Guardrail |
|---|---|---|
| 1 | **Structured extraction** from alert `description` / `instruction` text (e.g., "ice 0.25–0.5 in, 3 AM–noon") | JSON schema validation, results labeled "LLM-extracted", used only to corroborate. Never the sole basis for a threshold. |
| 2 | **Plain-language rationale** paragraph, paste-ready for email | **Grounding verifier:** every number, time, place and threshold in the text must exist in the evidence or recommendation JSON. Fail → regenerate once → fall back to template. |
| 3 | **Audience-variant message drafts** | Length, reading-level and required-elements checker (Section 9.2). |
| 4 | **Analyst agent** (tool-calling): "why not closure?", "what if onset is 2 hours earlier?", "who's affected?" | Tools: `evaluate`, `counterfactual`, `resolve_recipients`, `get_evidence`. The agent cannot write to the decision record. |
| 5 | **Embeddings + pgvector** for precedent search: similar past decisions and policy excerpts (OPM handbook text, agency directives) | Answers cite the retrieved record or document id. |

Eval set: `evals/` with about 20 fixture scenarios and automated checks for grounding, completeness and reading level, run in CI against a recorded-response mode.

---

## 12. UI screens

1. **Situation board:** map of facilities colored by recommended posture, active alert polygons, "Teleport facility to live alert" control, and a data-freshness indicator.
2. **Facility decision view:**
   - Posture card with decision-deadline countdown.
   - Inputs table (source, timestamp, age).
   - Threshold bars showing margin crossed.
   - Confidence with its components.
   - "What would change this."
   - Rationale paragraph with a copy button.
   - **Approve / Modify / Override (reason required).**
3. **Notification preview:** recipients table with include/exclude reason per person, variant previews, channel routing, simulated send, and live ack tracker.
4. **Decision record:** timeline, time-travel slider, chain-integrity badge, export.
5. **Thresholds:** the defensibility page, with sources, sensitivity plots and sign-off status.
6. **Analyst panel:** the tool-calling agent, with tool calls visible so judges can see it is grounded.

---

## 13. Repo layout

```
.
├── PROJECT_PLAN.md   README.md   THRESHOLDS.md (generated)   CLAUDE.md
├── docs/            verification-log.md, architecture.md, demo-script.md, akamai-usage.md, costs-and-teardown.md
├── backend/
│   ├── app/         api/, ingest/, engine/, notify/, llm/, records/, db/
│   ├── engine/thresholds.yaml
│   └── tests/       unit/, golden/, property/, contract/
├── frontend/
├── scripts/         seed.py, gen_thresholds_doc.py, record_fixtures.py, verify_chain.py
├── fixtures/        recorded NWS/USGS payloads (tests + labeled fallback)
├── evals/
├── deploy/          compose.prod.yaml, cloud-init / scripts (from starter kit), k8s/ (stretch)
├── .github/workflows/ci.yml, deploy.yml
├── .env.example     (no secrets committed, ever)
└── compose.yaml
```

---

## 14. Data model (core tables)

`facilities` · `employees` · `raw_observations` (source, url, issued_at, fetched_at, sha256, object_key) · `alerts` (parsed NWS alerts, linked to raw) · `gauge_readings` · `recommendations` · `decision_records` (chained) · `notification_packages` · `notification_recipients` (employee_id, included, reason, variant, channels, send_at) · `outbox` (simulated sends, acks) · `llm_calls` · `doc_chunks` (pgvector).

**API sketch:** `GET /facilities` · `GET /facilities/{id}/recommendation?as_of=` · `POST /facilities/{id}/decision` · `GET /facilities/{id}/notifications/preview` · `POST /notifications/{id}/send` (simulated) · `GET /records?facility_id=&as_of=` · `GET /records/verify` · `POST /analyst/chat` · `POST /demo/teleport`.

---

## 15. Phased plan (adjust hours to the actual event length)

**Gate rule: do not proceed past a phase while its gate is red.**

| Phase | Work | Gate |
|---|---|---|
| **0 — Kickoff (hr 0–1)** | Akamai signup via the HackMidwest link (**activate the account immediately**, it can be slow), get the team inference key at kickoff, repo init, CI skeleton, `.env.example`, read the starter-kit docs and `costs.md`, run the **[VERIFY]** items | `curl` to NWS works; one inference call works |
| **1 — Thin slice live (hr 1–5)** | NWS alert + point + gridpoint ingest → raw to Object Storage → Postgres. Minimal UI listing real alerts. **Deploy to Linode now** with Compose, Managed Postgres, Valkey. | Public URL shows live alerts, served from Akamai |
| **2 — Engine v0 (hr 4–10)** | Facility and roster seed, registry v0, alert-tier logic, posture + timing logic, decision record with hash chain, golden tests | A real alert produces a posture and a chained record |
| **3 — Depth (hr 9–16)** | Gridpoint quantitative thresholds, USGS/NWPS flood signal, confidence rules, counterfactuals, threshold docs generator | Recommendation JSON complete per Section 8.2 |
| **4 — Notifications (hr 14–21)** | Recipient resolver with reasons, variants, timing, simulator channels, ack tracking, human approval flow | Full path: recommendation → approve → package → outbox |
| **5 — LLM layer (hr 18–26)** | Extraction, grounded rationale with verifier, variant drafts, analyst agent, embeddings and precedent search, fallbacks | Grounding verifier blocks a deliberately bad draft in tests |
| **6 — Polish (hr 24–32)** | Map and UX, time-travel view, sensitivity plots, README, architecture diagram, `akamai-usage.md`, demo video, rehearse | Demo script runs twice cleanly on the live URL |
| **Final — Freeze** | Tag a release, record a backup video, verify teardown notes. **Do not tear down before judging.** | — |

---

## 16. Workstreams (collapse if the team is small)

- **A — Ingest and data:** NWS/USGS clients, caching, archive, seed data, fixtures.
- **B — Engine and thresholds:** pure engine, registry, confidence, counterfactuals, tests, `THRESHOLDS.md`.
- **C — Notifications and records:** recipient resolver, variants, simulators, decision record and chain.
- **D — Frontend:** map, decision view, record view, analyst panel.
- **E — Cloud and AI:** Akamai provisioning, CI/CD, deploy, `LLMClient`, extraction, grounded drafting, agent, embeddings.

Interfaces between streams are the Pydantic models in `backend/app/models/` and the DB schema. Agree on those in hour 1 and change them only by PR.

---

## 17. Testing

- **Golden tests:** recorded real NWS payloads → expected posture, thresholds crossed and recipient lists.
- **Property tests (hypothesis):** worse inputs never yield a milder posture (monotonicity); the same inputs always give an identical recommendation and hash (determinism); every employee appears in the recipient table with a reason.
- **Reproducibility test:** recompute from stored evidence and compare with the stored recommendation.
- **Chain test:** tamper with one record, then `verify_chain` must fail.
- **LLM tests:** grounding verifier rejects invented numbers; message checker rejects missing elements; template fallback activates when inference errors.
- **Contract test:** a scheduled job hits live NWS and checks that the schema we depend on still parses.

---

## 18. Risks and fallbacks

| Risk | Mitigation |
|---|---|
| No qualifying alert active during the demo | "Teleport facility" to a live alert elsewhere, broaden event types, and keep recorded-fixture replay clearly labeled as replay. |
| NWS rate limiting or outage | Valkey cache, ETags, backoff, and "using cached data from HH:MM" banner with a confidence downgrade. |
| Hosted inference slow, down, or model details differ from assumptions | `LLMClient` abstraction and template fallbacks, so the engine never depends on the LLM. |
| LLM hallucinated numbers | Grounding verifier, and the LLM never decides. |
| Credit burn / forgotten resources | Read `costs.md`, use the smallest plans that work, tag resources, set a billing alert, write `costs-and-teardown.md`. |
| Scope creep | Section 3 is law. Stretch items need a green gate and a team vote. |
| "You made up the thresholds" | Section 8.5 and 8.8: sources, sensitivity, backtest, and explicit sign-off flags. |
| Accidental real messages | Simulator adapters only, with real sends behind a flag limited to opted-in teammates. |

---

## 19. Demo script (about 5 minutes)

1. **Hook (20s):** "4:07 a.m., an ice storm is moving in. The manager has a forecast tab, a DOT map and a group text."
2. **Live data (40s):** Open the situation board on the public Akamai URL. Show real NWS alerts arriving. Teleport the facility to a live alert.
3. **Recommendation (60s):** Posture, countdown, every input with timestamp, the threshold crossed and by how much, confidence, and the "what would change this" panel. Copy the rationale paragraph.
4. **Human decision (30s):** Approve, then show an override that demands a reason.
5. **Notification package (60s):** Walk through the roster, including who was *excluded* and why (detail, leave, already teleworking, essential staff getting a different message), preview variants, show routing and the ack tracker.
6. **Decision record (45s):** Time-travel to "what was known at 03:58," verify the hash chain, and show that tampering is detected.
7. **Defensibility (20s):** The thresholds page with sources and a sensitivity plot, plus the honest "needs USDA sign-off" flags.
8. **Akamai + AI (30s):** Architecture slide: compute, Postgres/pgvector, Object Storage, Valkey, inference. Show the analyst agent calling the engine as a tool.

---

## 20. Definition of done

- [ ] Public URL on Akamai Cloud, pulling live NWS data
- [ ] At least one supplementary signal live (USGS / NWPS gauges)
- [ ] Graded recommendation with inputs, source + timestamp, threshold margin, confidence, what-would-change, and a paste-ready rationale
- [ ] Notification package with per-employee inclusion reasons, variants, timing, routing
- [ ] Hash-chained decision record with time-travel and verification
- [ ] `THRESHOLDS.md` generated, every threshold sourced or flagged for sign-off
- [ ] Inference used for extraction, grounded drafting and the tool-calling analyst, with fallbacks tested
- [ ] CI green, tests passing, secrets scan clean
- [ ] README with architecture, "How we used Akamai," judging crosswalk, demo video, limitations
- [ ] Teardown notes written, resources left running until judging ends

---

## 21. First tasks (do these in order)

1. Create the repo with the layout in Section 13, `.env.example`, and a CI workflow that runs lint and tests.
2. Sign up for Akamai Cloud and activate the account. Read the starter-kit docs listed in Section 4 and `docs/costs.md`.
3. Run the NWS `curl` commands from Section 6.1. Save three real alert payloads and one gridpoint payload to `fixtures/`.
4. Write the Pydantic models for `Facility`, `Employee`, `EvidenceItem`, `EvidenceBundle`, `Recommendation`, `DecisionRecord`. Agree on them as a team.
5. Implement the NWS client (User-Agent, ETag cache, backoff, raw-archive hook) plus a scheduled poller.
6. Stand up Compose locally (API, Postgres, Valkey), then deploy the same Compose to a Linode with Managed Postgres. **Get a public URL showing live alerts before building anything else.**
7. Resolve the **[VERIFY]** items and log the results in `docs/verification-log.md`.
8. Implement `evaluate()` v0 from alert tier and timing only, with golden tests, then add the decision record chain.
9. Only then move to Phase 3 and beyond.

When something in this plan conflicts with what the live APIs actually return, **trust the API, log the discrepancy, and update this file.**