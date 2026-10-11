# Provisional CMU challenge-cohort recovery comparison

Research evidence only. Production recovery prediction abstains; no recovery date is displayed.

CMU result integration remains provisional pending reconciliation of the source owner's existing submitted analysis scope and private-report publication interpretation. No source-permission or final clinical acceptance is inferred from this packet.

## Provenance and fixed protocol

Clean source: `ff561b7bbfe94411f71568f69c1ef4b0ff3e087d` (`git_dirty=false`). The scientific choices and splits were committed before corrected CMU scores in `af09ba3`. Subsequent changes correct censoring/publication metadata and integrate main. CMU protocol version2 changes version/exposure metadata only; every other config field and both split protocols remain unchanged. No post-score tuning, refit or recalibration.

Snapshot: `7c1429b102ebf5bcb5c0f94db0aba6c1e290d1b0b78aeae68c7105b3cfda38c3`.
Combined config: `7182114cf43e29827fa8c155b3fea0eb370e2cffc00337ebd4ac694d35d0ca30`.
Split protocol: `0f9b7b6f49ce382574ee3b1692ecbe4b9ce712991d1cd0ebef1376938d2e03bb`.
Fold plan: `f95b01edbd73c7511e517b03a1bf9e4a887d19f416b2a172b523b4eb2d790016`.
Lock: `1b290745f51cf459018c95226823b49db1422e08817402bfc111fef0c30b1297`; Python `3.12.13`.
Byte-identical runner receipt: [cmu.json](cmu.json), SHA256 `5a9606cb414f0fbc0d3c357386ac57dc3a60882a877565df0f611192ddf436dc`.

Private packet: `/Users/ezzyrappeport/hachi/runs/NavyOwl/recovery-cmu-minimized-01`. Private weights, assignments and participant predictions stay local. All 33 files and 7 directories have no group/other permission bits.

```sh
/Users/ezzyrappeport/hachi/runtime/navyowl/venv/bin/python -I -m hachi.models.recovery \
  --snapshot /Users/ezzyrappeport/hachi/data/derived/clinical-labels-2-cmu-common-cold-project-retrieved-2026-10-10-7c1429b102eb \
  --config configs/experiments/recovery/cmu.json \
  --output /Users/ezzyrappeport/hachi/runs/NavyOwl/recovery-cmu-minimized-01
```

The command ran in the isolated recovery worktree. Reproduction needs a new private output directory and the recorded clean source.

The endpoint is `outcomes-1-sustained-symptom-free-2d`: first day of an observed two-day symptom-free run, retrospectively confirmed only at the end of the second day. Retain resolved intervals (`S(L-1)-S(U)`); censor through the last observed symptomatic or intermediate day (`S(C)`), including conservatively across gaps. Exclude zero remaining follow-up. One first-observed-symptomatic end-of-day landmark per episode uses only the current source-native symptom score. Retrospective onset/category/test/resolution are not predictors. Eligibility still requires retrospective episode ascertainment and future follow-up.

Whole-person outer4/inner3/mintrain4/seed42 folds are assigned using identity-only full-roster projection before task filtering; only outer0 development participants have outcome/predictor reads. No test scoring, selection, refit or post-score calibration.

Constant daily training-cohort hazard versus ridge logistic hazard with intercept, log future day and static current symptoms; ridge0.1, maximum3000 iterations, tolerance1e-6, cluster bootstrap1000. This comparison does not isolate the added symptom contribution from time-shape differences.

Clock: `relative_to_challenge` (study day N = 2000-01-01 + N); no calendar alignment. Predictor: native `jackson_adjusted`, the baseline-adjusted eight-item Jackson total, available only at end of its study day. No app-severity conversion, wearable/date/serology/shedding joins or 7/14-day transfer.

The frozen primary horizon is2d, calibration1/2/3d, exports<=3d. Quarantine follow-up is5d (6d for influenza); each export day needs at least20 distinct training people known at risk and each fold at least20 training resolutions. Known at risk means C>=day for censoring or L>day for a resolved interval. These pre-score conservative research thresholds do not establish clinical accuracy or generalize beyond this challenge cohort.

## Development support and held-out comparison

**Aggregate disclosure (B3).** Previously published development audits repeated #8 endpoint categories. Combined with the existing source-wide #8 audits, those counts made test-partition outcome totals derivable. Both cohort receipts now record historical aggregate exposure. Removing category breakdowns cannot restore past blindness. Task eligibility correlates with source categories, so test-partition label totals remain roughly inferable from #8's whole-cohort audit; where eligibility coincides, some categories may be exactly inferable. No test-total subtraction is performed or published. No new test-outcome read/scoring is authorized, and no blind-final-test claim is made. Parent retains any decision about the compromised partition.

Publication receipt format3 allowlists #14 task eligibility and task-specific exclusions on development partitions, including per-fold audits. Full source-category counts remain only in runner-owned private `private-audit.json`. Disjoint validation task audits are summed once; no full-roster task eligibility audit is performed.

Development task support: 122 eligible resolved and 367 eligible censored episodes. Task-specific exclusions include 16 zero remaining future follow-up and 0 no observed symptomatic landmark. The known-unresolved bound precedes the final survey in 99 development episodes. Actual landmark wearable-day coverage: 0; no wearable predictors.

At 2d, 489 inner-validation episodes from 489 people: baseline censored NLL 0.657445; conditional 0.633204; paired conditional-minus-baseline -0.024242, participant-cluster percentile95% interval [-0.036830, -0.012342]. Lower is better. Bootstrap conditions on fitted models and this active split; it omits training/selection uncertainty. Small-fold intervals are descriptive.

| Inner fold | Train people | Train resolved episodes | Validation people / episodes | Export support days | Baseline NLL | Conditional NLL | Difference95% interval |
|---|---:|---:|---:|---:|---:|---:|---|
| 0 | 322 | 81 | 167 / 167 | 3 | 0.661158 | 0.636046 | [-0.046353, -0.005634] |
| 1 | 330 | 91 | 159 / 159 | 3 | 0.539787 | 0.528022 | [-0.033231, 0.009950] |
| 2 | 326 | 72 | 163 / 163 | 3 | 0.768412 | 0.732891 | [-0.054835, -0.016522] |

Training known-at-risk counts and resolved-event counts by every export day are in the receipt. Both optimizers converged in all folds. Horizon-straddling intervals supply only known pre-interval survival; day1-starting intervals crossing the horizon contribute no score information. This coarsening assumes non-informative observation, not established by these data.

## Calibration and uncertainty

Probabilities are unmodified. Unknown horizon outcomes retain interval identification bounds; none become negative labels. The receipt contains Brier identification bounds and bootstrap intervals for predicted means and both observed bounds.

| Fold | Day | Known / ambiguous | Baseline mean | Conditional mean (95% interval) | Observed resolution fraction bounds | Observed lower / upper bound95% intervals | Conditional Brier bounds |
|---|---:|---:|---:|---|---|---|---|
| 0 | 1 | 167 / 0 | 0.098301 | 0.113055 [0.109182, 0.116951] | [0.143713, 0.143713] | [0.095808, 0.197605] / [0.095808, 0.197605] | [0.119611, 0.119611] |
| 0 | 2 | 153 / 14 | 0.186939 | 0.193441 [0.187000, 0.199939] | [0.215569, 0.299401] | [0.149701, 0.281437] / [0.233533, 0.371257] | [0.164323, 0.214638] |
| 0 | 3 | 135 / 32 | 0.266864 | 0.257412 [0.249046, 0.265878] | [0.239521, 0.431138] | [0.167665, 0.305389] / [0.353293, 0.508982] | [0.175662, 0.263481] |
| 1 | 1 | 159 / 0 | 0.108205 | 0.132302 [0.126589, 0.137633] | [0.106918, 0.106918] | [0.062893, 0.157233] / [0.062893, 0.157233] | [0.094043, 0.094043] |
| 1 | 2 | 147 / 12 | 0.204702 | 0.221906 [0.212599, 0.230618] | [0.157233, 0.232704] | [0.100629, 0.213836] / [0.169811, 0.301887] | [0.133697, 0.174792] |
| 1 | 3 | 119 / 40 | 0.290757 | 0.290976 [0.278908, 0.302132] | [0.194969, 0.446541] | [0.132075, 0.257862] / [0.364780, 0.522013] | [0.163626, 0.270947] |
| 2 | 1 | 163 / 0 | 0.085207 | 0.102611 [0.100114, 0.105193] | [0.190184, 0.190184] | [0.134969, 0.251534] / [0.134969, 0.251534] | [0.159825, 0.159825] |
| 2 | 2 | 155 / 8 | 0.163155 | 0.178396 [0.174193, 0.182758] | [0.257669, 0.306748] | [0.196319, 0.325153] / [0.245399, 0.374233] | [0.192755, 0.224443] |
| 2 | 3 | 132 / 31 | 0.234460 | 0.240150 [0.234685, 0.245862] | [0.306748, 0.496933] | [0.239264, 0.374233] / [0.423313, 0.576687] | [0.209569, 0.308205] |

The conditional hazard model improves pooled two-day log loss within this challenge cohort, but calibration is inadequate for serving: folds0 and2 underpredict observed resolution at the primary horizon, and identification intervals widen at day3. No recalibration was fit after viewing scores. A positive research comparison is not evidence of app-level clinical accuracy or a long-horizon recovery forecast.

## Exports and remaining gates

489 conditional relative-day curves exported and reloaded with exact parity. Unreached quantiles are null: q0.25 156, median 489, q0.75 489. All outputs remain within per-fold supported follow-up; no exact recovery dates or extrapolated quantiles. Research artifact format2 pins native cohort/scale/features/clock and implementation hashes. Every production `predict` call returns `None`.

The private export audit is generated by the runner and independently matches the saved curve count. Public receipts omit source categories from every nested audit, not only the top-level audit. Scientific scores, support, calibration and all private research predictions are byte-for-byte or value-identical to the prior fixed-model run; only publication/provenance metadata changes. Published JSON is byte-identical to its private aggregate; no participant rows, identifiers, predictions or weights are published.

Required clinical/application gates remain: an independently accepted endpoint/split/privacy correction; prospectively ascertained recovery follow-up and calibrated inference on a relevant target population; validated app-native symptoms/artifact integration. Unsupported serving remains unavailable, and #14 is not marked delivered by this research packet.

## CMU methods attribution, reference and grants

CMU's Laboratory for the Study of Stress, Immunity, and Disease collected these data under Sheldon Cohen, PhD. Access was through the Common Cold Project website, supported by NCCIH AT006694. This follows the [official methods and funding guidance](https://www.cmu.edu/common-cold-project/how-to-cite-data-and-grants/index.html).

Reference: Laboratory for the Study of Stress, Immunity, and Disease. (2016). *Common Cold Project*. Retrieved from [commoncoldproject.com](http://www.commoncoldproject.com).

Acknowledgements for the studies contributing the daily Jackson inputs:

- Aggregation/access: NCCIH R01 AT006694-01.
- PCS1 and PCS2: NIMH R01 MH50429; clinical/regulatory support NIH 5M01 RR00056.
- PMBC: NHLBI P01 HL65111 and P01 HL65112.
- PCS3: NIAID R01 AI066367; clinical/regulatory support NIH UL1 RR024153 and UL1 TR000005. The official page prints variants TR0005/RT000005; its grant table gives TR000005.

The [label configuration](../../../configs/outcomes/cmu-common-cold-project.toml) excludes BCS from daily-symptom labels because it lacks these Jackson inputs. No supplementary biomarker assessments are analyzed here.

The [official daily-symptom methods](https://www.cmu.edu/common-cold-project/measures-by-study/assessment-of-infection-colds/daily-symptoms-in-quarantine.html) describe previous-day self-report collected at the end of quarantine days. This model consumes the supplied adjusted Jackson variable, not a recomputation from individual items. Hachi's score threshold and two-day symptom-free endpoint are prespecified research constructs, not a CMU-validated recovery criterion or clinical-cold diagnosis.

The [recorded registration](../../../configs/outcomes/cmu-common-cold-project.toml) states all three teammates submitted the Data Analysis Form on 2026-10-11. Exact submitted recovery/survival scope and the private-report publication classification are being confirmed with the source owner; submission alone is not a claim that an unavailable form's wording was inspected. The [CCP agreement](https://www.cmu.edu/common-cold-project/data/data-sharing-agreement/index.html) requires analysis registration and references for publications. No new form, external publication or expanded data access is implied by this report.
