# Ames historical backtesting and replay

Use **More tools → Replay a past storm**. Choose the normal-weather control, one of the seven curated weather events,
a discovered AMW disruption, or enter any date and time. The default is **04:00
America/Chicago**. Click **View historical weather**. Date/time changes clear the
old display immediately; older responses cannot replace a newer selection.
**Return to live** restores the current dashboard. Historical browsing is read-only:
it cannot record an operating decision, create notification packages, send messages,
or automatically request paid AI explanations/reviews. An explicit **Regenerate**
request can add an AI explanation to a selected immutable result.

The seven curated events remain examples with simulated recommendations/outcomes;
they are not verified closure decisions at the synthetic USDA facility. Their
original intraday snapshot APIs and fixture builder remain available. Arbitrary
date/time searches create exact intraday results on demand, rather than silently
choosing the nearest existing snapshot.

## Normal-weather control

**Jul 18, 2024 normal-weather control** is available in both replay tabs without an
archive download. The fixture retains unchanged AMW METAR rows from the checksummed
2024 source object in the frozen Ames dataset; it records the parent object, original
source hash, subset hash, public source URL and retrieval time. Its independent daily
outcome has 24/24 observed hours, no reported freezing precipitation or snow, and no
defined station-level disruption. Missing gust reports remain null, not zero.

Each selected-time report and hourly ribbon cell runs the current rules against only
the preceding twelve hours of observations, excluding readings less than fifteen
minutes old. The complete daily record is used only for the separate hindsight
outcome. The control shows observed temperature and wind charts and does not call
an inference provider or fetch missing weather. Forecasts and original warning
history are explicitly unavailable: **Normal** is the rules' fallback and **Yellow**
means incomplete evidence, rather than a hazard or verified all-clear. Replays remain
read-only and cannot notify employees or record decisions.

The **Feb 5, 2025 winter weather advisory** is labeled a **mild-weather case**, since
it includes winter hazards and is unsuitable as an ordinary-weather negative control.
This one quiet station day is illustrative: it is not office-decision evidence or a
false-alarm rate. Adding it does not change the frozen 7,470-case scoring cohort,
stored historical evaluations, or recorded human decisions.

## Completed local build

Measured on October 11, 2026:

- **10,968 observation-only daily evaluations**, September 30, 1996 through October
  10, 2026, inclusive. The 2020–2026 initial range and backward extension completed
  without failed source-download ranges. Completion means dates were processed;
  it does not mean every date has enough observations to grade.
- A separate small forecast reconstruction sample covers February 22, 2023 and
  January 8–12, 2024. This is **not a completed multi-year forecast backtest**.
- Under the current rules, the observation baseline has **7,470 gradable same-day
  comparisons**: 7,219/7,470 ordinary agreement (96.64%), balanced accuracy 72.05%,
  disruption recall 44.10%, 198 detected disruptions, 251 missed disruptions,
  7,021 true negatives, and zero false alarms against the defined station labels.
  The absence of forecasts makes this a weak benchmark of advance warning.
- 3,133 searches target another scheduled facility day (weekends); 351 lack complete
  outcome coverage; 14 lack adequate pre-evaluation inputs. These are excluded from
  impact scores. The small forecast sample is reported separately as **not enough
  data**. These results do not establish actual facility closure accuracy.

AMW's advertised station start is September 30, 1996. Supporting downloads span
1995–2026 because adjacent years supply UTC/local-day boundary observations. Dates
before the station start, current/future days, malformed times, and ambiguous or
nonexistent daylight-saving times produce explicit errors. An uncached archive is
unavailable unless **Download missing public archives** is enabled. Empty/partial
records remain distinguishable from quiet weather.

## Historical evidence and leakage boundaries

The bulk source is IEM's yearly routine/special METAR export for AMW. It supplies
temperature, apparent temperature, winds/gusts, visibility, precipitation, and
weather codes. Downloads use one concurrent yearly request, a 120-second timeout,
three attempts with bounded backoff, and compressed yearly caching. Prediction
inputs come only from the preceding twelve hours, with a **15-minute assumed
observation availability lag**. Actual ingestion times and original pre-correction
observation versions are not archived; this is an observation-based reconstruction.

Optional archive enrichment uses the existing NBS, SPC, road and RWIS adapters.
Source issue/report times after the selected instant are rejected. Observation
points beyond the cutoff are rejected as well. Forecast availability is conservatively
estimated as nominal run/product issue plus two hours; exact publication timestamps
are unavailable. Results are labeled **archived forecast reconstruction (estimated
availability)**, rather than verified forecast backtests. Missing forecasts do not
cause live NWS forecasts to be substituted.

Final VTEC event records can contain later changes to expiration or cancellation.
They are **excluded from recommendation inputs** until original alert/update
history can be reconstructed. Successful archive retrieval is not proof the
original alert state is known. The UI displays unavailable alert coverage.

Historical charts, relevant metrics, risks, explanations and analogs follow the
selected snapshot. Road summaries use retained historical inputs; missing geometry
and reports are labeled unavailable. Basemap tiles are geographic context, not
current road conditions. Camera feeds are never fetched for these reconstructions:
**Historical camera imagery unavailable** is shown. Separately saved human decisions
retain their original weather and decision-time camera frames.

The current facility configuration, hours and commute corridors remain a synthetic
scenario, not historical site conditions or historical employee attendance. No
historical facility outages, building damage, staffing or accessibility conditions
are available. Analog comparisons and proxy decisions are outcome/context displays,
not inputs to the deterministic recommendation engine.

## Independent outcomes and performance definitions

`AMW-local-disruption-v1` labels the full selected local day independently of the
recommendation thresholds. A disruption is observed if any of these occur:

- Reported station peak gust reaches 58 mph.
- At least two hourly freezing-precipitation flags occur.
- At least three hourly snow flags occur and daily visibility reaches ¼ mile.
- Apparent temperature reaches −35°F.

The daily outcome requires temperature, wind and METAR reports in all but two
daily hours, and no gap longer than three hours. DST days use their actual 23/25-hour
length. Prediction grading requires at least eight temperature-observation hours
in the prior twelve. A recommendation targeting another day is ungradable against
this day's evidence. Later daily observations are used only by outcome labeling,
never by prediction inputs. AMW labels miss off-station damage, corridor impacts,
snow totals and outages; exact closure/delay/telework ground truth is not inferred.
Hourly precipitation flags are inferred from METAR text, including remarks; they
are coarse station-evidence labels rather than certified ice/snow measurements.

Impact alignment maps NORMAL to no disruption and other postures to disruption.
Proxy agreement uses the same broad mapping, and reports exact status only for
comparable NORMAL/CLOSED/DELAYED_ARRIVAL/EARLY_DISMISSAL labels. Remote learning and
partial closures support broad agreement only; remote learning is not telework.
Unknown operating days are never treated as normal.

The UI/API report ordinary accuracy, balanced accuracy where both classes exist,
precision, recall, true positives/negatives, false alarms, misses, numerator and
denominator, date range, exclusions, and 95% Wilson intervals for ordinary accuracy.
Fewer than 30 observations or a single-class sample is labeled **not enough data**.
Balanced accuracy is primary because quiet days dominate ordinary accuracy.
Reconstruction types and evaluation clock times are kept separate. Year and hazard
breakdowns use the recommendation's highest-scoring hazard, with engine tie order.
No threshold tuning was performed. Future tuning requires chronological held-out
periods. Intervals do not adjust for correlated storm days.

## Local operating evidence found

Five institution-day records on three unique dates are stored in
`backend/data/historical_closures.json`, separate from weather inputs:

- Ames CSD and Nevada CSD: January 12, 2024 classes canceled.
- Iowa State University: January 12, 2024 partial campus closure.
- Iowa State University: January 30, 2019 closed except essential services;
  January 31 reopened at noon, mapped to delayed arrival.

The 2024 records come from [Ames Tribune reporting syndicated by AOL](https://www.aol.com/news/iowa-state-university-closes-campus-232924371.html).
Its January 11 publication timestamp establishes that the decisions were documented
before January 12 at 04:00, but is **not** the original announcement timestamp.
The 2019 evidence comes from the [official ISU Economics notice](https://www.econ.iastate.edu/classes-canceled-offices-closed),
corroborated by [IEM's dated university-closure feature](https://mesonet3.agron.iastate.edu/onsite/features/cat.php?day=2019-01-29).
The official notice does not expose an announcement timestamp or explicit year;
the dated IEM feature corroborates the 2019 episode. January 29 is not graded
because the notices describe different revised scopes for that day.

No verified dated Ames USDA closure history was found. The [Ames ARS/APHIS status
page](https://www.ars.usda.gov/midwest-area/ames/nadc/docs/location-support/ames-ars-and-aphis-operational-status/)
is a research lead, not historical ground truth. Official Ames/Nevada searches did
not yield a comprehensive historical archive. Holidays, planned calendar releases,
closures outside Story County, unrelated Ames-named schools, and anecdotal Reddit
posts were excluded. No explicitly normal weather-day operations were verified.

All five exact announcement timestamps are unknown. Three records have a dated
publication upper bound. Scores remain separate by institution/type/year/hazard,
and count both distinct institution-days and unique days. Using the same evidence
for two reconstruction types does not increase those distinct counts. School and
university policies differ; this closure-only sample cannot estimate specificity,
false-alarm rate or reliable balanced accuracy. The benchmark SHA identifies the
current evidence version; adding evidence regrades retained predictions without
changing their stored inputs or original artifacts.

## Storage, retention and build controls

Run `npm run setup` if dependencies are not installed. Build from the repo root:

```sh
npm run build:daily-history -- --start 2020-01-01 --online
npm run build:daily-history -- --start 1996-09-30 --end 2019-12-31 --online
npm run build:daily-history -- --resume BUILD_ID
```

Optional `--mode archive` enriches with forecast/road archives and takes more
requests. The UI exposes the same range builder, progress, cancel/resume actions,
failed ranges, and retry through a new build of the failed range. **Rebuild this
result** creates an additional immutable attempt for a selected date/time; enabling
downloads refreshes the AMW source. Missing forecast runs are negatively cached by
the existing adapters, so a stable absent run is not repeatedly downloaded.

Durable jobs resume at their next date after restart; startup marks interrupted
jobs rather than silently launching work. Only one UI build runs at a time. Use the
CLI while the API is stopped, or the UI while it runs; separate processes do not
share an in-memory worker lock. A changed rule/configuration version requires a new
build, preserving prior results. Identical date/time/rule/configuration requests
reuse their saved result. Each new rule version adds storage rather than overwriting
old evaluations. Keep the API bound locally; builds are public-data downloads.

Local files:

- `backend/var/closurecall.db`: compact evaluation summaries, content-addressed gzip
  snapshot artifacts, job state, existing decisions and camera archives.
- `backend/var/historical_sources/AMW-YEAR.json.gz`: normalized source batches with
  URL, fetch time, raw response hash and availability assumptions. This directory
  follows `DATABASE_PATH` if customized. These files are ignored by Git.
- `backend/data/historical_closures.json`: public proxy evidence committed with code.

Measured storage: yearly AMW sources **10.40 MiB**; compressed evaluations
approximately **85 MiB**, averaging **8.1 kB/result**. A complete year of evaluations
uses about **2.83 MiB** (2020: 2,965,081 compressed bytes; 2025: 2,959,927). Yearly
sources average about 0.35 MiB/year. Total SQLite size is about **230 MiB**, including
preexisting camera archives and indexes; it is not all new historical data.
The initial 2020–2026 observation build took **55 seconds** and backward extension
**177 seconds** on this machine; network/provider performance can vary. The five-day
forecast sample took about ten seconds with downloads, then about two seconds cached.

Default retention keeps results and source batches indefinitely; no historical
camera imagery is generated. Past-year source batches are cached indefinitely;
current-year sources refresh at most once per UTC day when online retrieval is
explicitly enabled. Source archives may apply later quality corrections: hashes
and retained normalized prediction inputs identify what the evaluation used, while
source revisions may limit exact reproduction of old outcome labeling. Existing
configured database cloud backups include evaluation artifacts, but yearly source
files are local and need separate backup. No new paid source, credentials or bulk
AI inference is required. Large archive-enrichment builds and optional cloud
storage/explicit AI requests can add runtime, request volume or existing-service costs.

## Verification and remaining gaps

Backend tests cover cutoff leakage, revised-alert exclusion, forecast publication
lag, exact evaluation times, DST, missing sources/outcomes, independent grading,
ordinary/severe conditions, clock/rule preservation, idempotence, cancellation,
resumption, failed-year suppression, metric denominators, proxy mapping and
read-only API boundaries. Frontend tests/typechecking/build verify chart behavior;
the local Chrome workflow is checked for curated/ordinary/severe dates, unavailable
dates, changed times, evidence, cameras and returning to live.
The final suite passed 180 backend tests and 15 frontend tests, and the production
frontend build/typecheck passed. Chrome checks also exercised rapid selection changes
and opening an existing decision's weather/camera archive from replay mode. That
review stays pinned and read-only; opening Notify staff restores the live context.

Unfinished data coverage: the full multi-year archived forecast build, original
alert issue/update timelines, historical facility operations/outages and camera
frames, comprehensive school/USDA operating history, and explicitly normal proxy
days. Only the observation baseline is built across the full supported range.

## Correction and recall-first thresholds (2026-10-11)

**The 7,470-day labels and observation-only results above overstate performance.** The yearly AMW download
stored each report's whole METAR (remarks included) as its weather codes, and weather flags were substring
matches. Remarks such as `LTG DSNT` (lightning distant) read as snow and `FZRANO` (freezing-rain sensor out) as
freezing rain. Re-deriving every day from the raw reports with only the present-weather group
(`adapters/historical_asos.py: present_weather`):

- **117** disruptive days in 30 years, not 449 (332 labels were remark artifacts; summer "snow" days fell from 53 to 7).
- The old 44% recall / 0 false alarms was largely circular: the same remark text triggered both the overnight
  freezing-precipitation rule and the label. Corrected, 04:00 observations alone catch **7.7%** (9/117).
- The live app is unaffected (IEM obhistory returns the present-weather codes only).

Because forecasts are the only way to see weather that starts after 04:00, the evaluation now adds the
archived NBM/NBS forecast that was already published at 04:00 (IEM, available from 2019). Thresholds were
tuned for **recall** on 2019-2022 and checked once on held-out 2023-2026:

| Thresholds | 2019-2022 recall | 2023-2026 recall (held out) | 2023-2026 false alarms |
|---|---|---|---|
| Before (2026-10-10.1) + forecasts | 65.2% (15/23) | 25.0% (3/12) | 13 |
| **Recall-first (2026-10-11.1)** + forecasts | **78.3% (18/23)** | **41.7% (5/12)** | 15 |

Changes in `config/thresholds.yaml` (marked `basis: policy`): forecast snow advisory 3 in -> 2 in; forecast
45 mph gust and forecast -20 F wind chill raised from minor to significant, so arrivals outside the morning
commute trigger early dismissal or telework instead of staying Normal. Held-out precision is 25% (about three
false alarms per disruption caught) on 12 disruptive days, so the interval is wide. Remaining misses are mostly
events the archived forecast did not show at 04:00 (for example freezing rain with low forecast precipitation
chances, or afternoon gusts forecast in the 40s).

Reproduce (needs the restored dataset; forecasts are cached in `var/backtest_http_cache`):

```sh
cd backend && .venv/Scripts/python -m scripts.recall_backtest --forecasts   # .venv/bin/python on Linux/macOS
```

The frozen cohort and its published releases still carry the old labels. Rebuilding a corrected cohort
(new version) and re-publishing it is a follow-up; existing frozen artifacts are not edited.

## Confirmed office-decision dataset (2026-10-11)

Decision scoring and AI-explanation sampling now use only reviewed official office
notices with dated corroboration (`confirmed-office-evidence-v1`). Current qualifying
proxy records are ISU nonessential offices closed January 30, 2019 and reopening
at noon January 31, 2019. Essential operations continued. The official notice and
IEM's dated University Closure feature corroborate these dates and scope.

Class cancellations and partial-campus/remote-flexibility notices are excluded:
they do not establish whether offices actually opened. Raw evidence remains retained
with exclusion reasons; historical weather archives and immutable evaluations are
preserved. The date-search event picker defaults to qualifying dates. The curated
storm timeline remains a separate weather reference, not decision ground truth.

This is a high-confidence documentary-evidence category, **not a calibrated 95%
probability**. Weather API observations establish conditions, not whether an office
operated. No weather-only inference, guessed normal day or numerical confidence is
promoted to a confirmed decision. No actual USDA operations are confirmed by these
proxy notices. Two records from one episode cannot establish decision accuracy,
false-alarm rates or reliable training performance. Independent station-weather
impact scores remain separate and retain weather-only days.

## Fixed 7,470-day safety and operational-loss experiment

Run `npm run analyze:risk` from the repository root. Optional assumed missed-event
cost ratios: `npm run analyze:risk -- --ratios 1 5 10 20 50`.
No AI calls, external weather requests, notification delivery or production changes
occur. The fixed manifest is `backend/var/cohorts/ames-7470-v1.json` (ignored).
It pins evaluation IDs, artifact hashes, summary hashes, rule/config hashes, unique
local dates and the 04:00 Central cutoff. Initial creation requires exactly 7,470
eligible observation-only dates; an unexpected count fails explicitly. Repeated
runs reuse the original evaluations, even when later attempts exist. Source archives
and excluded immutable evaluations remain stored separately. The UI distinguishes
the fixed analysis cohort from total archive coverage and forecast samples.

The cohort excludes 3,133 next-workday evaluations, 351 incomplete outcomes and 14
incomplete pre-evaluation inputs. Training is 1996–2018 (5,585 dates), validation
2019–2022 (939), and final testing 2023–2026 (939). Seven dates are purged around
split boundaries: a two-calendar-day gap on both sides and any identified consecutive
disruptive episode spanning a boundary. The full manifest remains 7,470 dates;
5,585 + 939 + 939 + 7 accounts for every date. No preprocessing/model fitting is
performed in this experiment: it varies stored signed rule-margin classification
cutoffs without altering scientific thresholds or rerunning the operating engine.
This is retrospective sensitivity analysis, not a newly trained AI predictor.

For each assumed cost ratio, select the lowest-loss candidate using validation
only, then evaluate that fixed candidate on final-test dates. Test outcomes never
choose the cutoff. Training results are reported as historical characterization.
These final-test dates were already inspected during earlier baseline backtesting;
this is not pristine prospective validation. No prospective model exists yet;
future model deployment requires an untouched, versioned future evaluation stream.
Reports contain per-split counts, confusion matrices, error rates, accuracy, balanced
accuracy, precision, recall, specificity, Wilson intervals, cost losses and annual/
hazard breakdowns. Wilson intervals do not correct correlated storm days. There
are only 20 disruptive final-test days, so disruption recall remains uncertain.

Completed local results: full-cohort baseline is unchanged (96.64% ordinary accuracy,
72.05% balanced accuracy, 44.10% recall). On the separate 939-day final-test subset,
existing rules catch 1 of 20 disruptions, miss 19, and produce zero false alarms.
Ratios 1:1, 5:1 and 10:1 select the unchanged margin cutoff. Ratios 20:1 and 50:1
select −75 percentage points of signed rule margin: 7 detected, 13 missed and 140
false alarms among 919 quiet days. Recall increases from 5% to 35%, with six extra
catches. At 20:1 assumed loss increases from 380 to 400; at 50:1 it falls from 950
to 790. This is evidence of a trade-off, not a generally improved model. Whole-cohort
44.10% recall must not be compared directly with final-subset recall as if the cohorts
were identical. No production cutoff has changed.

Cost weights are illustrative and unitless. Weather Type II errors may imply injury,
commuting or stranding exposure, but do not prove an unsafe operating decision.
Type I errors may delay services, unfinished work or revenue; closure is not assumed
to mean unpaid leave or permanent task/income loss. Remote or later work may recover
tasks; essential personnel may still travel during closure. Missing injury, crash,
facility, payroll and task-recoverability data are explicit. AI explanation prompts
preserve the deterministic posture and manager authority, and prohibit invented
financial losses, probabilities or reporting instructions.

Local report: `backend/var/analysis/ames-7470-v1-risk.json`; content-versioned reports
are retained alongside it. No credentials, contact configuration or generated data
are added to Git. An entirely new cohort/version is required for a different rule
experiment; old results and manifests must not be silently overwritten.

Verification for this experiment: 209 backend tests, 24 frontend tests and the
production frontend build passed. Chrome verified the 7,470-day cohort display,
chronological split counts, 20-day disruption sample warning, cost-ratio selection,
and the 50:1 final-test comparison. A regression test confirms later evaluation
attempts cannot replace the pinned original cohort. No production thresholds changed.
