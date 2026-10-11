# Hachi: what the evidence supports

Preparation for #23. Full issue acceptance remains open. This is a research
prototype; no diagnosis, treatment decision or clinically validated prediction.
Measured claims below are generated from the public manifest. The source ledger
pins report bytes, original producing receipts and proof limits. Recheck before
presenting; neither a closed issue nor this document grants scientific acceptance.

## Problem and intended experience

Wearable history can reveal changes, but a change alone does not establish illness.
Hachi aims to show a supported physiological forecast, compare it with actual future
observations and a personal baseline, and explain coverage and uncertainty. Symptoms
support a separate illness/recovery research path. Sleep schedules support conditional
simulation until measured alertness labels justify a personal prediction.

These are distinct tasks: physiology forecasts numerical signals; anomaly monitoring
measures deviation; illness predicts new symptom onset; recovery estimates time to a
prespecified resolution endpoint; sleep scenarios display assumptions. A positive
test date is a separate target. Missing surveys are unknown. Anomaly scores are never
infection probabilities. [Product scope](../PRODUCT.md), [evaluation](../EVALUATION.md).

## Architecture and leakage controls

Source admission and native ingestion feed versioned canonical observations and
features. A causal cutoff excludes unfinished observations and records created later,
including backdated records. Whole-participant splits and rolling origins keep future
labels separate from historical inputs. Model artifacts bind code, configuration,
data, protocol, features and receipts. The API returns provenance and explicit
unavailable states; the interface consumes the shared contract.

The intended chain is permitted data → causal features → frozen artifact → API →
interface. The delivered independent replay consumer reads an immutable saved result
with the live API stopped. Replay changes only replay metadata and retains the
original real/synthetic mode; fixture illustrations remain synthetic.
[Contracts](../CONTRACTS.md), [rehearsal source runbook](../../scripts/rehearsal/README.md).

## Real physiology development evidence

PMData is a permitted Fitbit research source. It is not Apple Watch validation, and
its illness status is unknown. This experiment forecasts next-day hourly mean heart
rate on prespecified development cutoffs. Source clock/availability are documented
assumptions. The outer test remains untouched.

Development cohort: 12 unique validation participants; 84 planned origins; 2016 scheduled target hours; 168 insufficient-history hours and 249 missing labels; 1599 eligible labeled hours scored by Chronos. [Evidence](CLAIMS.md#forecast-cohort).

The PMData outer test reserves 4 participants (source sealed flag: `True`). [Evidence](CLAIMS.md#sealed-test).

The forecast reports use: “95% intervals are participant-level bootstrap (1,000 resamples, seed 42).” [Evidence](CLAIMS.md#confidence-method).

Last-valid baseline: MAE 12.03 bpm, participant confidence interval [10.94, 13.01]; 1599 scored hours and 0 labeled abstentions. [Evidence](CLAIMS.md#last-valid).

Seasonal baseline: MAE 11.15 bpm, participant confidence interval [9.42, 12.94]; 1464 scored hours and 135 labeled abstentions. [Evidence](CLAIMS.md#seasonal).

Frozen causal tree: MAE 10.32 bpm, participant confidence interval [9.38, 11.30]; 1481 scored hours and 118 labeled abstentions. [Evidence](CLAIMS.md#tree).

Chronos zero-shot: MAE 8.94 bpm, participant confidence interval [7.69, 10.17]; 1599 scored hours and 0 labeled abstentions. [Evidence](CLAIMS.md#zero-shot).

Own-model errors use each model's available predictions. Compare improvement only
on common paired support, and show exclusions and abstention alongside error.

Chronos minus last-valid: paired MAE difference -3.09 bpm [-4.28, -2.06], on 1599 common target hours. Negative favors Chronos. [Evidence](CLAIMS.md#paired-last).

Chronos minus tree: paired MAE difference -1.29 bpm [-2.64, -0.06], on 1481 common target hours. Negative favors Chronos. [Evidence](CLAIMS.md#paired-tree).

Nominal central quantiles were 0.1 and 0.9. [Evidence](CLAIMS.md#interval-level).

The prespecified central interval observed coverage was 0.812 [0.779, 0.846], with width 29.42 bpm. [Evidence](CLAIMS.md#intervals).

The demonstrated CPU baseline has point-only outputs. Do not draw an uncertainty
band or borrow the pretrained candidate's measured interval coverage for that baseline.

## What pretraining and training contributed

Chronos actually ran zero-shot on causal contexts. WBM and MOMENT actually produced
frozen representations, followed by training the same phase-modulated ridge head on
handcrafted inputs, embeddings, or both. Train-only scaling/projection and identical
origins make the representation ablation interpretable.

The actually trained handcrafted ridge head achieved MAE 9.78 bpm [8.83, 10.74]. [Evidence](CLAIMS.md#trained-head).

Adding frozen WBM to that same head changed paired MAE by +0.22 bpm [-0.46, +0.96] on 1481 common hours; the interval includes zero. [Evidence](CLAIMS.md#wbm-no-gain).

Adding frozen MOMENT to that same head changed paired MAE by +0.53 bpm [-0.08, +1.08] on 1481 common hours; the interval includes zero. [Evidence](CLAIMS.md#moment-no-gain).

The trained-head contribution is distinct from a representation contribution. These
results do not establish added information from the frozen representations in this
forecasting task. Missing channels, device shift and mismatch between a weekly
representation and an hourly forecast limit interpretation; this is not a claim that
the encoders are useless. Pretraining overlap is unknown for Chronos/MOMENT and none
known for WBM. The separate accepted #12 experiment now supplies actual adaptation,
ensemble comparisons and development selection. The earlier head experiment remains
a distinct contribution, with its original support and limits.

## Accepted development selection and negative adaptation results

The accepted public #12 report extends the same frozen PMData protocol. Its incumbent
chain evaluates paired error and decile loss, coverage, abstention, latency and memory;
a challenger replaces the incumbent only when every gate passes. Root independently
replayed the saved Challenge estimates and verified original private file hashes and
the actual native selected loader. That acceptance covers development selection;
it does not independently recompute the original decile losses/runtime or accept a
final test. This preparation reads only committed public aggregates.

Development-selected `chronos-2-zero-shot-ctx720` uses 12 validation participants across 3 inner folds. Of 2016 expected hourly targets, 168 lack sufficient history and 249 lack labels, leaving 1599 scored points; 0 eligible points are abstained. [Evidence](CLAIMS.md#selected-support).

The selected development model reports MAE 8.05 bpm [7.15, 9.15] and RMSE 13.01 bpm [11.47, 14.56]. [Evidence](CLAIMS.md#selected-errors).

Native nominal 80% interval coverage is 0.782 [0.745, 0.811], with mean width 23.02 bpm [20.63, 25.62]. [Evidence](CLAIMS.md#selected-intervals).

Native intervals remain uncalibrated after selection. These selected-model numbers
are separate from the earlier zero-shot comparison and point-only CPU rehearsal.
The successful incumbent changes were:

`handcrafted-ridge-personal` versus `train-population-mean-v1`: paired ΔMAE -2.47 bpm [-4.17, -0.69] on 1599 common targets; rule result `promoted`. [Evidence](CLAIMS.md#selection-ridge).

`chronos-2-zero-shot-ctx168` versus `handcrafted-ridge-personal`: paired ΔMAE -1.33 bpm [-2.21, -0.64] on 1599 common targets; rule result `promoted`. [Evidence](CLAIMS.md#selection-context-middle).

`chronos-2-zero-shot-ctx720` versus `chronos-2-zero-shot-ctx168`: paired ΔMAE -0.34 bpm [-0.51, -0.16] on 1599 common targets; rule result `promoted`. [Evidence](CLAIMS.md#selection-context-long).

The adaptation contribution includes actual full-precision fine-tuning with AdamW
and best-checkpoint early stopping on a temporal holdout of training participants.
Learning rate and context were chosen on inner validation. Stacking fits constrained
decile weights on grouped out-of-fold points inside training participants, with
residual intervals fitted there as well. The public report retains optimizer, seed,
checkpoint, source/configuration and comparison-packet provenance. Private checkpoints
and sample artifacts are not redistributed here.

`chronos-2-finetuned` versus `chronos-2-zero-shot-ctx720`: paired ΔMAE +0.03 bpm [-0.14, +0.23] on 1599 common targets; rule result `kept_incumbent`. [Evidence](CLAIMS.md#adaptation-negative).

`ensemble-stacked` versus `chronos-2-zero-shot-ctx720`: paired ΔMAE -0.01 bpm [-0.06, +0.03] on 1599 common targets; rule result `kept_incumbent`. [Evidence](CLAIMS.md#stacking-negative).

`ensemble-equal-weight` versus `chronos-2-zero-shot-ctx720`: paired ΔMAE +0.58 bpm [+0.35, +0.81] on 1599 common targets; rule result `kept_incumbent`. Its interval coverage is 0.353 [0.323, 0.387], failing the coverage gate. [Evidence](CLAIMS.md#equal-weight-negative).

`chronos-2-zero-shot-steps` versus `chronos-2-zero-shot-ctx720`: paired ΔMAE +0.92 bpm [+0.36, +1.39] on 1599 common targets; rule result `kept_incumbent`. [Evidence](CLAIMS.md#steps-negative).

`chronos-2-embedding-ridge` versus `chronos-2-zero-shot-ctx720`: paired ΔMAE +1.22 bpm [+0.81, +1.64] on 1599 common targets; rule result `kept_incumbent`. [Evidence](CLAIMS.md#embedding-negative).

Those results retain the long-context zero-shot incumbent; an adapted model or ensemble
is not promoted. The rule was written after the earlier public baseline/zero-shot
results; the already-public representation heads are reported comparators only.

The report explicitly warns: “Thirteen candidates were compared on the same 12 participants and 7 days. The rule's confidence bounds are per comparison, not family-wise. Treat the selected model's validation numbers as optimistic until the sealed outer test is opened.” [Evidence](CLAIMS.md#selection-optimism).

Final #20 freeze, independent final evaluation and test opening remain root-owned
gates. PMData still supplies no illness labels and no real Apple transfer validation.

## Anomalies, burden and missingness

The Stanford clinical source uses shifted floating local clocks encoded with `Z`;
these are not actual UTC and cannot align different datasets' calendar dates.
The causal robust baseline is an adaptation with its own identity, not a claim to
reproduce upstream NightSignal exactly. Burden uses observed symptom-free surveys.

Stanford observed-control burden: 134 observed symptom-free days across 9 people; only 29 days across 3 people scored; 99 days lacked a resting measurement and 6 abstained at cold start. [Evidence](CLAIMS.md#anomaly-support).

There were 2 false-alert episodes intersecting controls and 3 alerted control days. Participant-weighted burden was 1.176 episodes per thirty scored control days [0.000, 3.529]. [Evidence](CLAIMS.md#anomaly-burden).

The separately pooled all-observed-days rate was 0.448 episodes per thirty observed days, including abstentions. [Evidence](CLAIMS.md#anomaly-denominator).

PMData cannot supply a healthy-alert denominator because illness status is unknown.
The Stanford controls have sparse supported resting measurements. Exercise, alcohol,
vaccination and travel were unavailable; absence of confounding is not established.
Keep cold-start, missingness and unsupported states visible during any demonstration.

## Illness, recovery and alertness remain separate gates

The accepted phase1 illness evidence is research-only and comes from a selected
retrospective illness-reporting cohort. Unlabeled controls supply no negative labels.
The short, middle and long horizons are the onset horizons fixed in the task protocol.
These rows repeat episodes across horizons and must never be summed into a new cohort.

24h illness development support: 30 people, 36 incident episodes, 170 eligible windows (36 positive / 134 negative). [Evidence](CLAIMS.md#onset-short).

48h illness development support: 30 people, 36 incident episodes, 157 eligible windows (72 positive / 85 negative). [Evidence](CLAIMS.md#onset-middle).

72h illness development support: 30 people, 36 incident episodes, 169 eligible windows (107 positive / 62 negative). [Evidence](CLAIMS.md#onset-long).

At the long horizon, 101/107 positive windows versus 3/62 negative windows had no prior survey in the source lookback. [Evidence](CLAIMS.md#survey-selection).

Past survey completion can predict whether the future window is eligible for a
negative label. The phase1 ablations do not establish an independent physiological
benefit at these selected windows. Retrospective classification metrics must not be
presented as transferable cold probabilities or population calibration.
Current exposed clinical outer partitions remain research-only. They are not a
repaired or pristine blind test; PMData's recorded sealed forecast test is a separate
task/source, with its own unopened final acceptance gate.

Research export parity: 81 artifacts reloaded, 4464 predictions replayed, 0 decision mismatches. [Evidence](CLAIMS.md#illness-parity).

The finalization report explicitly states: “No recovery adapter in this release accepts that packet.”. [Evidence](CLAIMS.md#recovery-exclusion).

Recovery still requires accepted censoring-aware follow-up and comparison with an
episode-duration/survival baseline. No recovery score from the superseded packet
appears here. CMU quantitative results are not admitted here. No CMU/recovery results
are promoted. The full initial scope remains incomplete.

## Published conditional sleep simulator

The original #15 conditional simulator is now published with an offline CLI and
source-bound SVG. Root independently exercised the CLI, checked implemented equations,
gap refusal and ambiguous-time handling, and inspected the rendered SVG at the accepted
source head. These are supplied root runtime receipts, not a new #23 execution or full
app rehearsal. [Accepted scoped runtime record](https://github.com/vibemonkies/hachi/pull/101),
[public description](../../src/hachi/scenarios/README.md).

The standalone simulator declares `status=ok`, `task=alertness`, `mode=simulation`, `data_mode=synthetic`, `validation=null` and `dataset_snapshot=null`. [Evidence](CLAIMS.md#simulation-metadata).

The pinned illustrative configuration is:

```toml
version = "two-process-v1"
tau_wake_hours = 18.2
tau_sleep_hours = 4.2
initial_pressure = 0.6
circadian_weight = 0.2
anchor_local_hour = 15
sample_minutes = 30
``` [Evidence](CLAIMS.md#simulation-parameters).

Each alternative uses a disclosed synthetic prior-sleep block, then awake/sleep
pressure propagation and a fixed circadian phase on elapsed UTC time. Missing local
times are refused; ambiguous times use the documented first occurrence. The relative
index is illustrative, with caffeine/light assumptions echoed but their effects not
modeled. Sleep quality, individual differences, chronotype and sleep inertia are omitted.
Changing assumptions can change the comparison; it cannot select a medically optimal
bedtime. The committed request is explicitly synthetic, with no participant observations.

The literature-derived concept cites
[Borbély et al., reappraisal](https://doi.org/10.1111/jsr.12371) and
[Daan, Beersma & Borbély, timing of human sleep](https://doi.org/10.1152/ajpregu.1984.246.2.R161).
Implementation is original; no borrowed software license is asserted. Root's equation
checks do not independently validate the paper's exact timing constants or fit parameters
to a population. Repeated ratings/PVT observations, train-only personal mapping and
held-out baseline evaluation remain missing. PMData daily fatigue is not hourly alertness
truth. Neither API nor full-app integration is delivered by the simulator merge.

## What the existing runtime receipts prove

These are historical source-bound receipts, not a newly completed #23 dry run.
They establish the independent rehearsal consumer, with the original CPU artifact.

The separate live CPU baseline API rehearsal compared 25 permitted PMData validation origins / 600 points against both frozen packet and independent evaluator, with 0 packet mismatches. [Evidence](CLAIMS.md#api-parity).

That HTTP rehearsal reported mean latency 0.171 s (range 0.104–0.214 s). [Evidence](CLAIMS.md#api-latency).

With the live API stopped, the saved real browser replay checked 24 points and 48 interval endpoints: 0 numeric, 0 time and 0 geometry mismatches. [Evidence](CLAIMS.md#replay-parity).

The historical CPU replay artifact is `hourly-last-valid-v1-141306001b16e168`, SHA256 `e7666ef0f4665006822f9ee9c0988a6de0df1633175ff217a27666ce6f66fa3b`. [Evidence](CLAIMS.md#replay-identity).

Generated Apple HTTP transport preserved the original sparse abstention and dense exact-inference behavior: source measurement row ``| 105,120 points, 12/hour | 8.742 s | 0.705 s | 0.645 s | `INSUFFICIENT_HISTORY` at original gates |``. [Evidence](CLAIMS.md#apple-transport).

Generated Apple transport retains `DEVICE_SHIFT`, explicit unvalidated-source
rationale and the original admission gates. It proves transport/exact inference for
that receipt; it proves no real Apple accuracy or consented case. Full app root
integration remains #17. See [DEMO.md](../DEMO.md) for a future rehearsal and its stop
conditions, and the [privacy receipts](../../reports/verification/privacy/README.md)
for generated deletion/remote-cleanup evidence. No current GPU job was run for this
preparation.

## Failures to retain in the story

Chronos was worse than the tree for 3 of 12 validation participants; the largest participant MAE difference was +2.89 bpm. [Evidence](CLAIMS.md#failure-tail).

The adapter clipped 19 upper quantiles to the registered physiological bound. [Evidence](CLAIMS.md#quantile-failure).

The representation comparisons lack demonstrated benefit. The anomaly path often
abstains. Illness labels are subject to survey-observation selection. Sparse generated
Apple inputs remain unavailable despite faster transport. Unsupported clinical or
scenario requests must display the actual reason. A missing replay cache must show an
error, never silently become a synthetic or live result. These are observed limits,
not hidden exceptions to the product scope.

## Attribution, privacy and the late personal case

PMData: Thambawita et al., *PMData: A Sports Logging Dataset*,
[source paper](https://doi.org/10.1145/3339825.3394926),
[dataset](https://doi.org/10.17605/OSF.IO/VX4BK). The registry binds the stricter
noncommercial Creative Commons reading because source license statements conflict.
Attribute the source, link the license and describe Hachi's canonicalization changes.

Stanford phase1: Mishra et al., *Pre-symptomatic detection of COVID-19 from smartwatch
data*, [source paper](https://doi.org/10.1038/s41551-020-00640-6). Public research
download is recorded; no explicit data license was found. Use only the admitted
noncommercial research scope with citation, not an inferred redistribution grant.

Chronos: [pinned checkpoint](https://huggingface.co/amazon/chronos-2/tree/29ec3766d36d6f73f0696f85560a422f50e8498c),
Apache license recorded in its accepted report. MOMENT:
[pinned checkpoint](https://huggingface.co/AutonLab/MOMENT-1-large/tree/ca58581bc7bea2ebed4e80dc0a3e4b8b609c6ecc),
MIT terms recorded. WBM:
[pinned checkpoint](https://huggingface.co/MyHeartCounts/openmhc-wbm-dp/tree/5db7e4598e1d1da3cdaeb04dce5e9b1ccaf21334),
[OpenMHC](https://arxiv.org/abs/2607.16235),
[Apple design reference](https://arxiv.org/abs/2507.00191). WBM distribution/repository
license statements conflict; the accepted run applies research-only use, no checkpoint
or derived-model redistribution and no medical-advice use until clarified. NightSignal:
[upstream code](https://github.com/StanfordBioinformatics/wearable-infection).
Source/version/license records are pinned in the ledger and [research registry](../RESEARCH.md).

Raw exports, participant identifiers, rows, predictions and weights remain in approved
private storage. Public materials show aggregates and distinctly synthetic examples.
No real chart screenshots or participant dates appear in this preparation. The API is
an operator-local service, not a participant-authentication system; generated cleanup
proof does not establish physical-media/backup erasure or personal-data transfer consent.

The friend's case is a late, separately consented retrospective held-out case. Analysis
and display permission are separate. A teammate holds the withheld future measurements;
onset uncertainty, cutoffs and healthy periods must be prespecified, predictions saved
before reveal, and failures retained without tuning. One person's case cannot establish
population sensitivity, clinical accuracy or generalization. The actual export/timeline,
consents and frozen accepted system are missing, so no case result is shown.

## Close with the remaining required experiment

Use the accepted development selection as input to the final freeze, then evaluate
the untouched forecast cohort under root's scientific/test-opening control. Obtain
adequate clinical labels/follow-up and independently observed negatives. Integrate the
same accepted artifact into the published app, complete the separately consented case,
then rehearse the live and offline paths. Presenter roles below are proposals pending
the humans' confirmation, not a claim of availability.

The [full roadmap gate map](GATES.md) retains every required milestone. Optional
dataset review and prospective logging do not satisfy these missing requirements.
