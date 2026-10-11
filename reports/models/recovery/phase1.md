# Stanford phase1 recovery comparison

**Research implementation and private outputs delivered; clinical recovery remains unavailable.**
The fixed symptom model shows no demonstrated advantage over the simple training-cohort
survival baseline. Its seven-day censored negative log likelihood is 0.375575 versus 0.375065
for the baseline (lower is better). The conditional-minus-baseline difference is +0.000511,
with participant-cluster 95% interval [-0.057237,+0.041182]. This is development validation
only, conditional on fitted models and the active outer split; the interval is not a final
population accuracy guarantee. No model was selected, retuned, calibrated after scoring,
refitted, or installed for serving.

The canonical endpoint audit is 59 episodes: 15 sustained two-day resolutions, 19 followed
right-censored episodes, and 25 with no follow-up. A current symptomatic survey and future
follow-up are required for this prospective landmark task. Across the entire roster's
label audit, only 24 episodes qualify (7 resolved / 17 censored); 8 have no observed symptomatic
landmark and 2 have no future follow-up after it. This aggregate input audit is not an outer
test evaluation. The full 121-person roster was split before eligibility filtering; the
agreed plan hash is `13dd73b4b3f2b6beabe105c5e577e86e935fa68edfdc117d8e9ebdc7c772fa5e`.
Outer 0's test remains sealed.

The three disjoint inner validation cohorts contain 17 episodes from 16 people, including
only 4 resolved episodes. Seven-day resolution is identified for all 17, with only one
resolution by that horizon. Original full resolution intervals remain interval-censored in
the training likelihood; no exact dates were invented.

| Inner fold | Training people / resolved episodes | Validation people / episodes / resolved | Baseline NLL | Symptom NLL | Difference95% interval |
|---|---:|---:|---:|---:|---:|
|0|11 /1|5 /5 /3|1.142924|1.068141|[-0.226193,+0.004653]|
|1|10 /3|6 /7 /1|0.039075|0.101600|[+0.028594,+0.099983]|
|2|11 /4|5 /5 /0|0.077592|0.066575|[-0.014506,-0.007921]|

All six fits converged. Research export support stops at 14 days in every fold, with the
precommitted requirement that at least five distinct training people have label follow-up
through each supported day. This is a follow-up/extrapolation limit, **not evidence that
there are adequate recovery events or representative training participants**. The receipt
contains the exact calibration estimates, Brier identification bounds and cluster
uncertainty at 3/7/14 days. Seven-day observed resolution proportions by validation fold are
20%, 0%, 0%; baseline predictions average 1.22%, 3.83%, 7.47%, and symptom predictions average
1.32%, 9.56%, 6.44%. Fold sizes are too small to establish calibration.

Private outputs contain 17 bounded conditional survival curves. All 25th/50th/75th
percentiles are null: none is reached within the supported 14 days. Model reloads reproduce
every saved curve and quantile, and the existing `RecoveryPayload` contract rejects
unsupported horizons. Relative days are exported; calendar recovery dates are never
produced. The artifact's serving `predict` always abstains. No wearables enter this primary
comparison; paired-day counts merely confirm available same-person records.

The source uses shifted floating local clocks represented as Z. These are **not actual UTC**
and support no calendar alignment with other datasets. Retrospective onset is used only
for episode association and label construction. Symptoms are available at the end of
their described local day. This is a retrospectively ascertained episode cohort; live
ongoing-episode admission and later cutoffs have not been validated. Unsurveyed controls
have no negative labels. Phase 2 has no
recovery follow-up; no CMU, DREAMT, GLOBEM, CovIdentify or friend-case data was analyzed.
Independent observation/censoring remains an assumption; a lone symptom-free report
cannot confirm the sustained endpoint. This outcome requires a larger permitted cohort
with enough prospectively observed recovery events and independent validation before
production recovery can be considered ready. #14 remains open.

Exact evidence:

- Clean source: `af7e26bb1abf27d3175669251bd78c2ac40e78c6`.
- Snapshot: `clinical-labels-2-stanford-covid19-wearables-2020-nbe-6a864b03b2d3`, SHA-256
  `6a864b03b2d3ddf05abc42b699679dba39f1909bad2c3053c4b8adf4108faf09`.
- Frozen canonical combined config: `b388747e9662e3f699bebf2ac0f3863f748f5c225f9014b56921a4784ea9b314`.
- Shared protocol: `60a4345a6feb8f4a192e6aec718e4b364d2f22a93ad8d227e1645d092ec6e82c`.
- Python 3.12.13, CPU only; runtime 3.893 seconds. The lock and every implementation file
  are hashed in [the aggregate receipt](phase1.json).
- Approved private packet: `/Users/ezzyrappeport/hachi/runs/NavyOwl/recovery-phase1-02`.
  Fold plans/assignments, models, participant predictions and scores stay there (mode 600
  files/mode 700 directories). Only aggregate evidence is in Git.

Reproduction command from the clean source above:

```sh
UV_PROJECT_ENVIRONMENT="$HOME/hachi/runtime/navyowl/venv" \
UV_CACHE_DIR="$HOME/hachi/runtime/navyowl/cache" \
uv run python -I -m hachi.models.recovery \
  --snapshot "$HOME/hachi/data/derived/clinical-labels-2-stanford-covid19-wearables-2020-nbe-6a864b03b2d3" \
  --config configs/experiments/recovery/phase1.json \
  --output "$HOME/hachi/runs/NavyOwl/recovery-phase1-unique"
```

Use a new private output directory. The runner refuses dirty source, a changed common
protocol, snapshot/fold mismatch, unsupported score scale/availability, invalid likelihood
inputs, nonconverged exports, or artifact parity failure. Focused tests and repository
checks are recorded in the PR; they prove implementation behavior, not clinical adequacy.
