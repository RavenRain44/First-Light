# Preserved backtesting metrics

Frozen cohort: 7,470 weather days, evaluated at 04:00 America/Chicago.

Baseline accuracy: **96.64%**. Balanced accuracy: **72.05%**. Disruption recall: **44.10%**.

Confusion counts: 198 caught disruptions, 7021 correct normal days, 0 false alarms, 251 missed disruptions.

This measures weather disruption agreement, not verified historical office closures or injury risk. High overall accuracy is driven by many normal-weather days. The baseline remains preserved; no production thresholds are replaced by whichever result has the highest headline accuracy.

`results.json` retains baseline metrics and validation-selected cost scenarios, with their held-out results and limitations. Candidate offsets are retrospective rule-margin sensitivity experiments, not trained AI or full engine reruns. Do not pick thresholds by maximizing final-test accuracy. Compare recall, false alarms and assumed weighted loss alongside accuracy.
