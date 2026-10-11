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

{{forecast-cohort}}

{{sealed-test}}

{{confidence-method}}

{{last-valid}}

{{seasonal}}

{{tree}}

{{zero-shot}}

Own-model errors use each model's available predictions. Compare improvement only
on common paired support, and show exclusions and abstention alongside error.

{{paired-last}}

{{paired-tree}}

{{interval-level}}

{{intervals}}

The demonstrated CPU baseline has point-only outputs. Do not draw an uncertainty
band or borrow the pretrained candidate's measured interval coverage for that baseline.

## What pretraining and training contributed

Chronos actually ran zero-shot on causal contexts. WBM and MOMENT actually produced
frozen representations, followed by training the same phase-modulated ridge head on
handcrafted inputs, embeddings, or both. Train-only scaling/projection and identical
origins make the representation ablation interpretable.

{{trained-head}}

{{wbm-no-gain}}

{{moment-no-gain}}

The trained-head contribution is distinct from a representation contribution. These
results do not establish added information from the frozen representations in this
forecasting task. Missing channels, device shift and mismatch between a weekly
representation and an hourly forecast limit interpretation; this is not a claim that
the encoders are useless. Pretraining overlap is unknown for Chronos/MOMENT and none
known for WBM. No selected adapted/ensemble export is admitted to this presentation;
actual #12 adaptation, export, uncertainty/cost-based selection and #20 acceptance
remain required. Do not replace those gates with this simpler head experiment.

## Anomalies, burden and missingness

The Stanford clinical source uses shifted floating local clocks encoded with `Z`;
these are not actual UTC and cannot align different datasets' calendar dates.
The causal robust baseline is an adaptation with its own identity, not a claim to
reproduce upstream NightSignal exactly. Burden uses observed symptom-free surveys.

{{anomaly-support}}

{{anomaly-burden}}

{{anomaly-denominator}}

PMData cannot supply a healthy-alert denominator because illness status is unknown.
The Stanford controls have sparse supported resting measurements. Exercise, alcohol,
vaccination and travel were unavailable; absence of confounding is not established.
Keep cold-start, missingness and unsupported states visible during any demonstration.

## Illness, recovery and alertness remain separate gates

The accepted phase1 illness evidence is research-only and comes from a selected
retrospective illness-reporting cohort. Unlabeled controls supply no negative labels.
The short, middle and long horizons are the onset horizons fixed in the task protocol.
These rows repeat episodes across horizons and must never be summed into a new cohort.

{{onset-short}}

{{onset-middle}}

{{onset-long}}

{{survey-selection}}

Past survey completion can predict whether the future window is eligible for a
negative label. The phase1 ablations do not establish an independent physiological
benefit at these selected windows. Retrospective classification metrics must not be
presented as transferable cold probabilities or population calibration.

{{illness-parity}}

{{recovery-exclusion}}

Recovery still requires accepted censoring-aware follow-up and comparison with an
episode-duration/survival baseline. No recovery score from the superseded packet
appears here. CMU scope results remain pending. Sleep scenarios remain a conditional
simulation proposal pending the separately owned #15 evidence/publication; no measured
personal-alertness accuracy is claimed. The full initial scope remains incomplete.

## What the existing runtime receipts prove

These are historical source-bound receipts, not a newly completed #23 dry run.
They establish the independent rehearsal consumer, with the original CPU artifact.

{{api-parity}}

{{api-latency}}

{{replay-parity}}

{{replay-identity}}

{{apple-transport}}

Generated Apple transport retains `DEVICE_SHIFT`, explicit unvalidated-source
rationale and the original admission gates. It proves transport/exact inference for
that receipt; it proves no real Apple accuracy or consented case. Full app root
integration remains #17. See [DEMO.md](../DEMO.md) for a future rehearsal and its stop
conditions, and the [privacy receipts](../../reports/verification/privacy/README.md)
for generated deletion/remote-cleanup evidence. No current GPU job was run for this
preparation.

## Failures to retain in the story

{{failure-tail}}

{{quantile-failure}}

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

Freeze and independently reproduce the complete supported candidate selection, then
evaluate the untouched cohort under root's scientific/test-opening control. Obtain
adequate clinical labels/follow-up and independently observed negatives. Integrate the
same accepted artifact into the published app, complete the separately consented case,
then rehearse the live and offline paths. Presenter roles below are proposals pending
the humans' confirmation, not a claim of availability.

The [full roadmap gate map](GATES.md) retains every required milestone. Optional
dataset review and prospective logging do not satisfy these missing requirements.
