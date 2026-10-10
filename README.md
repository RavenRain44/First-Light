# Closure Call

Weather-driven facility operating-status decision support for the **USDA AI Challenge, Hack Midwest 2026**
("Closure Call: Weather-Driven Facility Decisions and Notification").

Built by Landen, Isaac, Caleb, Casey and Collin.

> When severe weather threatens a federal facility, how does the decision to close happen fast enough,
> consistently enough, and with a clear enough record of why?

Closure Call does **not** automate the decision. It puts every input a manager needs in one place, recommends an
OPM-aligned posture from deterministic, cited thresholds, explains it in a paste-ready paragraph, and writes an
immutable, reconstructable record of what was known, when, and what the human decided.

Scope: **Iowa only**, one synthetic facility (USDA Service Center, Ames), two hazards handled well
(**winter/ice** and **high wind / severe thunderstorm**) plus an optional third (**extreme cold**).

## What's real and what's synthetic

| Real (live APIs or archives) | Synthetic |
|---|---|
| NWS active alerts and gridded forecasts (api.weather.gov) | The facility profile (`backend/data/facility.json`) |
| AMW ASOS observations, Iowa DOT road conditions, RWIS pavement sensors, NWS warning archive, archived NBM forecasts, SPC outlooks, Local Storm Reports (Iowa Environmental Mesonet) | The 25-person roster (`backend/data/employees.json`), including details, travel and telework |
| Seven historical Story County events, each verified against the NWS VTEC archive | Every "recommended posture" in the backtest (*simulated by rules*, not real USDA decisions) |
| Decisions recorded through the UI (labelled "real (recorded in this system)") | Commute corridor lines (approximate geometry) |

## Quick start

Prerequisites: Python 3.11+ (tested on 3.14), Node 18+ (tested on 24).

```bash
npm run setup      # dependencies, .env, and historical library for Replay
npm run dev        # API on http://localhost:8000, dashboard on http://localhost:5173
```

`make setup` / `make dev` do the same where GNU make exists. Windows has no make; use the npm scripts.

Setup also builds the historical library from the committed cache, so Replay, analogs and backtests
are ready on first launch. This build runs offline and does not change `DEMO_MODE` in your `.env`.

Set `NWS_USER_AGENT` in `.env` to your app name and a contact (NWS asks every client to identify itself).

### Build the historical library (replay, analogs, backtest)

```bash
npm run build:history                 # or: cd backend && .venv/Scripts/python -m scripts.build_history
```

This verifies each event in the IEM VTEC archive and replays it hourly (~270 evaluations, about 5 minutes online).
Every response is cached in `backend/fixtures/http_cache/` (gzip, committed). After that the build also runs
fully offline in about 20 seconds:

```bash
DEMO_MODE=true npm run build:history
```

### Run the demo offline

```bash
DEMO_MODE=true npm run dev
```

In demo mode every source is served from the committed cache. "Live" is pinned to the moment the cached live data
was fetched, so the demo is identical days later. **Live Check is the exception: it always calls the real NWS API.**
To refresh the cached "live" moment before a demo, run once online (`npm run dev`, click *Re-evaluate now*).

### Tests

```bash
npm test           # 50 backend tests: interval expansion, units, thresholds and margins, posture timing,
                   # confidence, counterfactuals, analogs, snapshot immutability, AI validation/fallback,
                   # and an end-to-end evaluation of the 2020 derecho from fixtures (offline)
```

## Environment variables (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `NWS_USER_AGENT` | app name + repo URL | Required by api.weather.gov |
| `DEMO_MODE` | `false` | Serve everything except Live Check from `backend/fixtures/http_cache` |
| `REFRESH_INTERVAL_SECONDS` | `0` | Periodic background live re-evaluation (0 = off) |
| `SNAPSHOT_STALE_SECONDS` | `600` | `GET /api/snapshot/latest` re-evaluates when the latest live snapshot is older |
| `LIVE_CACHE_TTL_SECONDS` | `600` | Live HTTP cache TTL (IEM asks clients not to hammer it; archives are cached forever) |
| `DATABASE_PATH` | `backend/var/closurecall.db` | SQLite file |
| `MODEL_PROVIDER` | `none` | `anthropic`, `bedrock`, `openai` (any OpenAI-compatible endpoint) or `none` |
| `MODEL_ID` | provider default | e.g. `claude-sonnet-5-5`; required for Bedrock |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `AWS_REGION` | | Provider credentials (Bedrock uses the AWS credential chain) |

The dashboard works fully with **no API key**: the deterministic template rationale is used and labelled as such.

## How a recommendation is made

```
adapters (NWS, IEM)  ->  normalized inputs (value, unit, source, URL, fetched_at, source time)
   -> signals (forecast totals/maxima with hourly exceedance windows, observations, roads)
   -> threshold rules (config/thresholds.yaml): triggered?, margin abs/%, peak time, window
   -> hazard scores 0-100 and levels (minor / significant / extreme)
   -> timing: each level's window vs. AM commute 06-08, facility hours 07:30-16:30, PM commute 16-18
   -> posture: NORMAL | DELAYED_ARRIVAL | EARLY_DISMISSAL | TELEWORK | CLOSED (with OPM label)
   -> confidence (completeness, freshness, forecast/obs/alert agreement, alert certainty)
   -> "what would change this" (rules re-run with each input moved past its threshold)
   -> Strands agent explains it (never decides)  ->  immutable snapshot
```

- **Timing matters.** The same hazard maps to different postures by when it hits: warning-level ice from 03:00-05:00
  (+3 h road recovery) is a delayed arrival; 05:00-09:00 is telework; a High Wind Warning from 14:00 is an early
  dismissal; a Tornado Warning in effect during work hours is a closure with shelter-in-place guidance.
- **Decision day.** Before noon the decision is about today; after noon (if today is quiet) it is about the next
  workday. Weekends roll to Monday.
- **The AI never decides.** One Strands agent (`backend/ai/agent.py`) with five read-only tools over the current
  snapshot (`get_snapshot_summary`, `get_triggered_rules`, `get_alerts`, `get_road_conditions`, `get_analogs`)
  returns strict JSON (Pydantic). Every number in the rationale must exist in the snapshot. On failure it retries
  once with feedback, then falls back to the template. The model id and prompt version are stored on the snapshot.

## The decision record

Every evaluation writes an immutable `snapshot` row: all normalized inputs with provenance, source statuses,
signals, rule results, hazard scores, posture, confidence, counterfactuals, analogs, the AI text, model id, prompt
version, the SHA-256 of `thresholds.yaml`, and a SHA-256 of the whole content. SQLite triggers reject any `UPDATE`
or `DELETE` (only simulated backtest rows may be deleted, so history can be rebuilt). Human decisions go in an
append-only `decision` table (accept, or override with a required reason). `GET /api/record/{snapshot_id}` returns
both, re-verifies the content hash, and says whether the thresholds have changed since.

## Backtest (simulated by rules)

Recommendation at 04:00 local on the impact day vs. what happened (LSRs within 25 mi, AMW ASOS, Iowa DOT):

| Event | 04:00 posture | Observed impact | Verdict |
|---|---|---|---|
| Aug 10, 2020 derecho | NORMAL | severe | **missed at 04:00**; first flagged 11:00 CDT when the warning was issued (the forecasts did not see it; AMW lost power) |
| Dec 15, 2021 high wind / derecho | EARLY_DISMISSAL | severe | consistent |
| Dec 21-23, 2022 blizzard | TELEWORK | severe | consistent |
| Feb 22, 2023 ice storm | CLOSED | severe | consistent |
| Jan 8-9, 2024 winter storm | TELEWORK | severe | consistent |
| Mar 4-5, 2025 blizzard + high wind | CLOSED | severe | consistent |
| Feb 5, 2025 advisory (control) | DELAYED_ARRIVAL | limited | **possible over-call** |

The derecho miss and the advisory over-call are kept on purpose: thresholds are defended with evidence, not hidden.

## Threshold anchors

All cutoffs live in [`backend/config/thresholds.yaml`](backend/config/thresholds.yaml) with `anchor`, `source_url`,
`basis` (official / policy) and `verified`. **verified: true** means we read the cited primary source and it states
the value or definition:

- NWS Instruction 10-511 (severe thunderstorm and tornado warnings; 58 mph / 50 kt, destructive 80 mph):
  https://www.weather.gov/media/directives/010_pdfs/pd01005011curr.pdf
- NWS Instruction 10-513 (winter products; ice storm "usually 0.25 in or greater", blizzard 35 mph and < 1/4 mi):
  https://www.weather.gov/media/directives/010_pdfs/pd01005013curr.pdf
- NWS Instruction 10-515 (non-precipitation products; high wind warning 40 mph sustained / 58 mph gusts, wind advisory 30-39 mph, extreme cold):
  https://www.weather.gov/media/directives/010_pdfs/pd01005015curr.pdf
- OPM, *Governmentwide Dismissal and Closure Procedures* (December 2025), Section IV operating-status categories:
  https://www.opm.gov/policy-data-oversight/pay-leave/reference-materials/handbooks/dcdismissal.pdf
- NBM text bulletin element units used to read archived forecasts: https://vlab.noaa.gov/web/mdl/nbm-textcard-v4.2

**Still `verified: false`** (shown with a ⚠ badge in the UI): forecast ice >= 0.10 in (SPIA-based policy);
snow >= 6 in / 12 h, >= 3 in / 24 h, >= 12 in / 24 h (DMX local criteria are published as an interactive map we could
not machine-read); observed freezing precipitation and ice accretion; all five Iowa DOT road-condition cutoffs
(the categories are Iowa DOT's, the ranking and cutoffs are ours); RWIS ice sensors; convective watches and SPC
ENH/MDT outlooks; forecast gust >= 45 mph; wind chill <= -20 F and <= -35 F (DMX Appendix B values not verified).

## Data sources

- NWS API: https://www.weather.gov/documentation/services-web-api (`/points`, `/alerts/active`, `/gridpoints`)
- Iowa Environmental Mesonet API: https://mesonet.agron.iastate.edu/api/1/docs (currents, obhistory,
  iowa_winter_roadcond, rwis, nws/outlook_by_point, nws/lsrs_by_point, mos) and the VTEC events-by-UGC service
  https://mesonet.agron.iastate.edu/json/vtec_events_byugc.php
- Real response samples and their field shapes: [`backend/fixtures/probe/SHAPES.md`](backend/fixtures/probe/SHAPES.md)
  (regenerate with `python -m scripts.probe_endpoints`)

## API

| Route | |
|---|---|
| `GET /api/facility` | facility, roster summary ("expected in building N of M assigned"), roster |
| `GET /api/snapshot/latest` | latest live snapshot (re-evaluates if stale) |
| `POST /api/evaluate` | `{mode: live|replay, as_of?, event_id?}` -> new snapshot |
| `GET /api/snapshot/{id}`, `GET /api/snapshots` | full snapshot / history list |
| `GET /api/record/{id}` | snapshot + human decisions + integrity check |
| `GET /api/timeseries?snapshot_id=` | observed + forecast series, threshold lines, commute/hours windows |
| `GET /api/roads?as_of=` | Iowa DOT segments GeoJSON with corridor matches + corridor table |
| `GET /api/history/events`, `GET /api/history/events/{id}`, `GET /api/history/events/{id}/replay?as_of=` | backtest library and replay |
| `GET /api/analogs?snapshot_id=` | top 3 similar past events |
| `POST /api/decisions`, `GET /api/decisions` | record / list human decisions |
| `GET /api/live-check/alerts`, `POST /api/live-check/evaluate` | national alerts and what-if evaluation |
| `GET /api/thresholds` | registry with anchors, verified flags, backtest summary |
| `POST /api/notifications/preview` | **501** stub: the notification package is the next phase |

## Repository layout

```
backend/
  app/        FastAPI app, routers, SQLModel tables, snapshot service, facility/roster
  adapters/   base interface + nws, iem_obs, iem_roads (roads + RWIS), iem_vtec (archive + SPC), iem_mos, iem_lsr, cache
  engine/     normalize, features, scoring, posture, confidence, counterfactual, analogs, evaluate
  ai/         Strands agent, snapshot tools, prompts/schema, deterministic fallback
  config/     thresholds.yaml
  data/       facility.json, employees.json (synthetic)
  fixtures/   probe/ (real samples), http_cache/ (gzip cache, demo mode), history/ (event exports)
  scripts/    probe_endpoints, build_history, make_e2e_fixture, compact_cache
  tests/
frontend/     React + Vite + TypeScript + Tailwind + Recharts + React-Leaflet
```

`PROJECT_PLAN.md`, `docs/`, `deploy/` and `compose.yaml` are from the team's earlier plan and are not used by this build.

## Next: notification package

Hooks are in place: the roster model separates *assigned* from *where people actually are this week* (details in and
out, travel, telework), each employee has contact channels and accessibility needs, and every send will be logged
against a snapshot and decision id. `POST /api/notifications/preview` describes the planned shape.
