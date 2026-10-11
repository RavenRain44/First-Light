# Historical chart cross-check — October 11, 2026

Checked the locally retained evidence without live weather requests, AI calls or notifications. The operational database and immutable historical artifacts were read without updating their decisions or measurements.

## Coverage

- All seven curated storm timelines: 265 retained snapshots (36 derecho, 38 ice storm, 37 December blizzard, 39 January snowstorm, 37 December high wind, 39 March blizzard, 39 mild advisory).
- July 18, 2024 normal-weather control: 24 hourly evaluations from retained station observations.
- Frozen baseline: all 7,470 evaluation artifacts, verifying their manifest SHA-256 hashes before reading them.
- Total: 7,759 evaluations. The frontend chart-data audit processed 24,408 metric instances and 271,891 numeric chart values, including calculated series and recorded scalar observations.

## Findings and fixes

The API's series values and timestamps matched their normalized snapshot inputs, with no source/transport mismatches. Observation timestamps after evaluation were excluded. Forecast inputs were limited to the chart's stated range. Frontend raw series remained unchanged, and recorded numeric rule peaks matched their chart series when compared at the recorded peak time, allowing the engine's documented rounding.

Fixed three issues:

1. Sustained-wind rules were not mapped to their own numeric curve. They now select sustained wind, not gusts, for threshold emphasis.
2. Archived cold snapshots could retain a calculated wind-chill decision value without a separate feels-like input series. Charts now reproduce the recorded calculation from retained forecast temperature and wind, label its provenance, and preserve any explicit feels-like series.
3. The API's threshold reference metadata used current configuration. It now uses the snapshot's recorded rule values. The visible frontend reference lines already used recorded rules.

Some broad-timeline peaks differ from a rule's value because the chart includes older observations or forecasts beyond that rule's evaluated interval. Those context measurements are valid; a new note explains this distinction. A chart shows one selected numeric rule, so other rules for the same measurement are not all drawn simultaneously. Categorical alerts/outlooks and missing-timestamp road aggregates are not invented numeric curves.

After fixes, the chart-value audit reported zero mismatches. Regression tests cover sustained wind, calculated feels-like, explicit series preservation, and historical threshold values. Backend tests, frontend tests and production build passed; browser replay tests cover graph selection, historical times, event switches and exact-minute searches.

This verifies consistency between stored inputs, recorded rules and graphs. It does not independently establish that every original weather observation or forecast was correct, or that a weather disruption was a confirmed office closure. Archived forecast absence remains visible; current forecasts are never substituted for it.
