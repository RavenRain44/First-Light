# FirstLight threshold registry

Generated from `backend/engine/thresholds.yaml` (sha256:cfb85f929d32). Do not edit by hand.

> Operational values labeled `agency_policy_assumption` are hypotheses for the prototype. They require written sign-off from a USDA safety or continuity official before operational use.

| ID | Hazard / metric | Trigger | Level / floor | Authority | Sign-off |
|---|---|---:|---|---|---|
| [alert_advisory](#alert_advisory) | other / `alert_tier` | advisory NWS product tier | L2 | [agency_policy_assumption](https://www.weather.gov/documentation/services-web-alerts) | Required |
| [alert_watch](#alert_watch) | other / `alert_tier` | watch NWS product tier | L2 | [agency_policy_assumption](https://www.weather.gov/safety/thunderstorm-ww) | Required |
| [alert_warning](#alert_warning) | other / `alert_tier` | warning NWS product tier | L3 | [agency_policy_assumption](https://www.weather.gov/safety/thunderstorm-ww) | Required |
| [ice_accum_ge_0_10in](#ice_accum_ge_0_10in) | winter / `ice_accumulation_in` | 0.1 in | L2 | [agency_policy_assumption](https://www.weather.gov/safety/winter-ice-frost) | Required |
| [ice_accum_ge_0_25in](#ice_accum_ge_0_25in) | winter / `ice_accumulation_in` | 0.25 in | L3 / DELAYED_ARRIVAL | [agency_policy_assumption](https://www.weather.gov/safety/winter-ice-frost) | Required |
| [ice_accum_ge_0_50in](#ice_accum_ge_0_50in) | winter / `ice_accumulation_in` | 0.5 in | L4 / CLOSED | [agency_policy_assumption](https://www.weather.gov/safety/winter-ice-frost) | Required |
| [snow_ge_3in](#snow_ge_3in) | winter / `snowfall_in` | 3.0 in | L2 | [agency_policy_assumption](https://www.weather.gov/safety/winter) | Required |
| [snow_ge_6in](#snow_ge_6in) | winter / `snowfall_in` | 6.0 in | L3 | [agency_policy_assumption](https://www.weather.gov/safety/winter) | Required |
| [wind_gust_ge_46mph](#wind_gust_ge_46mph) | convective / `wind_gust_mph` | 46.0 mph | L2 | [agency_policy_assumption](https://www.weather.gov/safety/wind-ww) | Required |
| [wind_gust_ge_58mph](#wind_gust_ge_58mph) | convective / `wind_gust_mph` | 58.0 mph | L3 | [nws_definition](https://www.weather.gov/safety/thunderstorm) | Verified source |
| [wind_gust_ge_75mph](#wind_gust_ge_75mph) | convective / `wind_gust_mph` | 75.0 mph | L4 / CLOSED | [agency_policy_assumption](https://www.weather.gov/safety/wind) | Required |
| [sustained_wind_ge_31mph](#sustained_wind_ge_31mph) | convective / `wind_speed_mph` | 31.0 mph | L2 | [agency_policy_assumption](https://www.weather.gov/safety/wind-ww) | Required |
| [sustained_wind_ge_40mph](#sustained_wind_ge_40mph) | convective / `wind_speed_mph` | 40.0 mph | L3 | [agency_policy_assumption](https://www.weather.gov/safety/wind-ww) | Required |
| [hail_ge_1in](#hail_ge_1in) | convective / `hail_in` | 1.0 in | L3 | [nws_definition](https://www.weather.gov/safety/thunderstorm) | Verified source |
| [wind_chill_local](#wind_chill_local) | winter / `wind_chill_f` | -20.0 degF | L2 | [agency_policy_assumption](https://www.weather.gov/safety/cold-wind-chill-chart) | Required |
| [flood_action](#flood_action) | flood / `flood_category` | action NWPS category | L1 | [nws_definition](https://api.water.noaa.gov/about/api) | Verified source |
| [flood_minor](#flood_minor) | flood / `flood_category` | minor NWPS category | L2 | [agency_policy_assumption](https://api.water.noaa.gov/about/api) | Required |
| [flood_moderate](#flood_moderate) | flood / `flood_category` | moderate NWPS category | L3 | [agency_policy_assumption](https://api.water.noaa.gov/about/api) | Required |
| [flood_major](#flood_major) | flood / `flood_category` | major NWPS category | L4 / CLOSED | [agency_policy_assumption](https://api.water.noaa.gov/about/api) | Required |
| [posture_opm_categories](#posture_opm_categories) | other / `posture_ladder` | OPM operating status | L0 | [opm_category](https://www.opm.gov/policy-data-oversight/snow-dismissal-procedures/) | Verified source |

## Registry entries

### alert_advisory

- Hazard / metric: `other` / `alert_tier`
- Trigger: `advisory NWS product tier`; severity level `2`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/documentation/services-web-alerts
- Summary: NWS alerts expose event, severity, certainty, urgency, and response fields; FirstLight maps advisories to level 2 for decision support.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Mapping an advisory to an operational level is a policy assumption.

### alert_watch

- Hazard / metric: `other` / `alert_tier`
- Trigger: `watch NWS product tier`; severity level `2`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/thunderstorm-ww
- Summary: A watch means conditions are favorable; FirstLight treats it as an elevated planning trigger rather than an instruction to close.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Operational mapping requires agency sign-off.

### alert_warning

- Hazard / metric: `other` / `alert_tier`
- Trigger: `warning NWS product tier`; severity level `3`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/thunderstorm-ww
- Summary: A warning means the hazard is occurring or imminent; FirstLight maps warnings to level 3.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: The alert is authoritative; the closure posture mapping requires agency sign-off.

### ice_accum_ge_0_10in

- Hazard / metric: `winter` / `ice_accumulation_in`
- Trigger: `0.1 in`; severity level `2`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/winter-ice-frost
- Summary: Small ice accretions can make untreated surfaces hazardous; the 0.10-inch planning trigger is conservative.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: NWS warning criteria vary by Weather Forecast Office.

### ice_accum_ge_0_25in

- Hazard / metric: `winter` / `ice_accumulation_in`
- Trigger: `0.25 in`; severity level `3`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/winter-ice-frost
- Summary: One-quarter inch is a common ice-storm impact anchor, but local warning criteria and impacts vary.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Confirm against the local WFO and agency continuity policy.

### ice_accum_ge_0_50in

- Hazard / metric: `winter` / `ice_accumulation_in`
- Trigger: `0.5 in`; severity level `4`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/winter-ice-frost
- Summary: One-half inch of accretion is used as a high-impact operational assumption.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Requires USDA safety or continuity sign-off.

### snow_ge_3in

- Hazard / metric: `winter` / `snowfall_in`
- Trigger: `3.0 in`; severity level `2`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/winter
- Summary: Snow impacts depend on local climatology, treatment, timing, and local WFO criteria.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Planning value only; local calibration is required.

### snow_ge_6in

- Hazard / metric: `winter` / `snowfall_in`
- Trigger: `6.0 in`; severity level `3`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/winter
- Summary: Six inches is an operational impact anchor rather than a nationwide NWS warning criterion.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Requires local WFO calibration and agency sign-off.

### wind_gust_ge_46mph

- Hazard / metric: `convective` / `wind_gust_mph`
- Trigger: `46.0 mph`; severity level `2`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/wind-ww
- Summary: NWS offices commonly use wind-advisory ranges near this value; exact criteria vary locally.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Calibrate to the responsible WFO.

### wind_gust_ge_58mph

- Hazard / metric: `convective` / `wind_gust_mph`
- Trigger: `58.0 mph`; severity level `3`
- Source type: `nws_definition`
- Source: https://www.weather.gov/safety/thunderstorm
- Summary: NWS defines a severe thunderstorm using winds of at least 58 mph and/or hail at least one inch in diameter.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: Not required for the cited definition
- Notes: This is a severe-thunderstorm definition, not by itself a federal closure rule.

### wind_gust_ge_75mph

- Hazard / metric: `convective` / `wind_gust_mph`
- Trigger: `75.0 mph`; severity level `4`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/wind
- Summary: A 75 mph forecast gust is treated as an extreme facility and commute impact.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Requires USDA safety or continuity sign-off.

### sustained_wind_ge_31mph

- Hazard / metric: `convective` / `wind_speed_mph`
- Trigger: `31.0 mph`; severity level `2`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/wind-ww
- Summary: Local Wind Advisory criteria vary; 31 mph is retained as a conservative planning baseline.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Local WFO criteria control.

### sustained_wind_ge_40mph

- Hazard / metric: `convective` / `wind_speed_mph`
- Trigger: `40.0 mph`; severity level `3`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/wind-ww
- Summary: Local High Wind Warning criteria vary; 40 mph is an operational baseline.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Local WFO criteria and agency policy must be applied.

### hail_ge_1in

- Hazard / metric: `convective` / `hail_in`
- Trigger: `1.0 in`; severity level `3`
- Source type: `nws_definition`
- Source: https://www.weather.gov/safety/thunderstorm
- Summary: NWS severe thunderstorm criteria include hail at least one inch in diameter.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: Not required for the cited definition
- Notes: Event definition, not a closure requirement.

### wind_chill_local

- Hazard / metric: `winter` / `wind_chill_f`
- Trigger: `-20.0 degF`; severity level `2`
- Source type: `agency_policy_assumption`
- Source: https://www.weather.gov/safety/cold-wind-chill-chart
- Summary: Cold-product criteria vary by geography; this placeholder must be replaced by the responsible WFO criteria.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Cold remains corroborating evidence until a less-than comparator and local policy are configured.

### flood_action

- Hazard / metric: `flood` / `flood_category`
- Trigger: `action NWPS category`; severity level `1`
- Source type: `nws_definition`
- Source: https://api.water.noaa.gov/about/api
- Summary: NWPS publishes gauge flood category levels and observed and forecast stage products.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: Not required for the cited definition
- Notes: Facility exposure scales the operational impact.

### flood_minor

- Hazard / metric: `flood` / `flood_category`
- Trigger: `minor NWPS category`; severity level `2`
- Source type: `agency_policy_assumption`
- Source: https://api.water.noaa.gov/about/api
- Summary: Minor is an official NWPS flood category; FirstLight maps it to level 2.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Posture mapping requires agency sign-off.

### flood_moderate

- Hazard / metric: `flood` / `flood_category`
- Trigger: `moderate NWPS category`; severity level `3`
- Source type: `agency_policy_assumption`
- Source: https://api.water.noaa.gov/about/api
- Summary: Moderate is an official NWPS category; level 3 is the FirstLight operational mapping.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Requires facility-specific exposure review.

### flood_major

- Hazard / metric: `flood` / `flood_category`
- Trigger: `major NWPS category`; severity level `4`
- Source type: `agency_policy_assumption`
- Source: https://api.water.noaa.gov/about/api
- Summary: Major is an official NWPS category; closure is a FirstLight policy assumption.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: REQUIRED before operational use
- Notes: Requires USDA safety or continuity sign-off and site-specific flood exposure review.

### posture_opm_categories

- Hazard / metric: `other` / `posture_ladder`
- Trigger: `OPM operating status`; severity level `0`
- Source type: `opm_category`
- Source: https://www.opm.gov/policy-data-oversight/snow-dismissal-procedures/
- Summary: OPM publishes open, unscheduled leave or telework, delayed arrival, early departure, and closure operating-status categories for the Washington Capital Beltway.
- Retrieved: 2026-10-10; verified by: FirstLight team
- Sign-off: Not required for the cited definition
- Notes: Outside the Beltway, employees follow their agency's announcements.

## Sensitivity

The application exposes `GET /api/thresholds/sensitivity?metric=...`, which sweeps each numeric trigger and displays exactly where severity changes. This is intentionally not presented as statistical validation. Local WFO criteria, facility exposure, road treatment, and agency policy must be reviewed before production use.
