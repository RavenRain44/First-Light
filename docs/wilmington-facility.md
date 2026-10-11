# Wilmington demonstration facility

Choose **Wilmington, NC** in the selector next to the Closure Call logo. The
dashboard, staff counts, roads, replay events, decisions, notification drafts,
and backtesting views follow the selected facility. Wilmington uses Eastern
time; Ames uses Central time. Changing facilities stops replay playback and
discards pending requests from the previous site. An edited, unsaved decision
or communication draft prompts before switching.

The Wilmington profile is fictional. It represents an office/laboratory near
College Road and UNCW at 34.2257, -77.8750, with 270 fictitious assigned staff.
Operating hours and commute windows are configurable. The profile does not
identify a real USDA building, certify its elevation or flood zone, or establish
an approved emergency plan.

## Weather and access information

- NWS Wilmington (ILM office, NCZ107/NCC129) supplies point forecasts and alerts.
- ILM airport observations and KILM archived forecast runs come through IEM.
- NOAA NWPS's WLON7 gauge supplies regional tidal-river observations, forecasts,
  and station-specific flood stages. Values are feet above MLLW at the gauge,
  not flood depth at the facility. Tide height includes influences besides
  storm surge. A regional stage crossing prompts monitoring and route checks.
- Original NWS Hurricane Local Statements provide supplemental regional
  context. Individual impacts in the statement do not automatically apply
  to the facility.
- DriveNC supplies reported road events and available cameras when configured.
  The retired NCDOT traffic-prod endpoint is not used.

### DriveNC configuration

Request a developer key through [DriveNC's developer documentation](https://www.drivenc.gov/developers/doc).
Configure `NCDOT_API_KEY` in secure environment settings, or your ignored local
`.env`. Never add the key to tracked files. Restart the backend after changing
environment variables. Cloud configuration changes must be reviewed, saved,
and published to become reusable; saving a draft alone does not configure the
running process.

The app remains usable without this key, and explicitly marks road and camera
coverage unavailable. Missing reports are not proof of clear roads. Events are
matched to the facility's demonstration commute corridors. A reported full
closure is distinguished from a lane closure or traffic restriction. Corridor
polylines are approximate demonstration routes; confirm exact affected routes
with the original DriveNC report before making a real operating decision.

NC pavement-sensor and historical road/camera coverage have not been verified.
The app does not fabricate equivalent Iowa ice-sensor measurements.

## Coastal decision support

Wilmington has a separately versioned policy overlay for tropical storms,
hurricanes, surge/coastal flooding, inland/flash flooding, and commute access.
Official alert definitions are distinct from this synthetic facility's policy
for selecting an operating posture. Ames retains its existing policy.

The preparation horizon extends to 72 hours. Watches, heavy-rain monitoring,
and regional gauge crossings support preparation; the manager reviews local
timing and access before deciding. A warning's effective time does not establish
when hazardous winds reach the facility. Flood-warning expiration does not
verify that a road has reopened. Follow official emergency instructions and a
verified facility emergency plan.

Cooper readiness describes urgency and awareness separately from the suggested
operating posture. The dashboard preserves confidence, people expected,
decision date, and weather time. Relevant charts highlight the evidence behind
the recommendation: wind for tropical conditions, rain and gauges for flooding,
and road evidence for access disruptions. Gauge identities, units, datums,
observations, and forecasts remain separate.

Akamai explains the saved evidence and deterministic suggestion. The facility
manager makes the final decision and explicitly approves communications.
Insufficient or backup evidence stays labeled and can require a decision reason.

## Historical replay and validation

Wilmington has its own curated event catalog and normal-weather control.
Retained originals include KILM forecast runs and ILM METAR observations;
each fixture records provenance and checksums. Original forecast availability
uses the documented publication estimate already used by the forecast adapters.

Only evidence available by the selected evaluation time supports a replay.
Current NWS, NWPS, DriveNC, and camera feeds are not substituted into old events.
Original hurricane-warning and surge/road archive coverage varies and is shown
as a gap. Final storm reports and revised historical water levels can support
outcome research, not pre-event recommendations.
Historical storm comparisons are withheld from replay briefs because their
original outcome publication times are not verified. Live comparisons remain available.

The normal control verifies ordinary airport weather rather than claiming
complete regional flood or road coverage. Station-only historical evidence
cannot establish coastal operational accuracy. Wilmington datasets, cohorts,
source archives, and jobs are facility-scoped; Ames scores are not Wilmington
validation. Historical replays and hypothetical live checks cannot record
operating decisions or create communication packages.

## Development checks

From the repository root:

```sh
DEMO_MODE=true MODEL_PROVIDER=none npm test
npm --prefix frontend test
npm --prefix frontend run build
PLAYWRIGHT_BROWSERS_PATH=/tmp/closurecall-playwright-browsers npm --prefix frontend run test:browser
```

`MODEL_PROVIDER=none` prevents paid inference during checks. Production judging
continues to use Akamai, with the existing optional AWS fallback. Optional
weather providers do not change the inference provider.
