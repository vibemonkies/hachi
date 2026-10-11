# Original WBM and MOMENT development heads

The seven original producer files were admitted by their frozen SHA256 pins: exact request order and native arrays, pinned checkpoints and runtime receipts, parquet values/metadata, and MOMENT's fully observed eight-hour patch support. WBM has 256 components and MOMENT has 1024. Both support all 147 original contexts. Each CPU head also receives four cutoff-safe survey-history features. No clinical encoder fitting, dimension search or GPU work occurred in this lane.

CPU heads ran at `9e6a108d4719ddccb6ec9dd6f3b6a7ac66477b49` under unchanged prescore comparison `937c6765e61663edbb431c73e5a07bc97bf3afaced5e993a689e8efd70e3ecd6`. Each family fitted 18 heads and withheld nine because context-supported inner1 calibration has zero negative outcome windows. The scored subset covers 17/30 eligible validation participants and 19/36 incident episodes, with 91/87/94 windows at 24/48/72h. Inner2 validation has no negatives; its within-fold ranking metrics are unavailable.

[wbm.json](wbm.json) and [moment.json](moment.json) contain re-derived counts, AUPRC/AUROC, Brier/reliability, PPV/sensitivity, alerts, negative-day burden, interval lead time and participant uncertainty, plus complete support gates and eligible denominators. The strict compiler verifies original features, source bytes, complete split/run manifests, all causal validation features/labels, fitting/calibration inputs and saved artifact math. Base-only replay at the exact archived source reloads 18 artifacts and 816 predictions per family, with no NumPy or scikit-learn and no changed alerts. Maximum probability differences are `8.881784197001252e-16` for WBM and `1.850741782050136e-13` for MOMENT; both pass the frozen 1e-12 tolerance. Receipts: [wbm-base-replay.json](wbm-base-replay.json), [moment-base-replay.json](moment-base-replay.json).

These selected illness-survey cohort estimates do not establish physiological added value or population calibration. Survey participation is a strong confound; pretrained cohort overlap is unknown. The calibration burden cap is a threshold-selection criterion inside training, not a guarantee about untouched validation. No scores were adjusted to satisfy that cap. No final winner, outer test, friend case or serving promotion was used. #13 remains open for accepted complete comparisons, independent negative calibration and final held-out/serving gates. The shifted floating local clock represented as Z is not actual UTC; COVID-specific labels are not performance claims for all colds.

## Reproduce

Use the clean archived scoring source above and its locked baselines environment. Original private source/request/return files and all clinical joins, predictions and artifacts stay outside Git.

```sh
python -m hachi.models.illness.pretrained_run --family wbm_hr \
  --snapshot "$PRIVATE_PHASE1_SNAPSHOT" --context-packet "$PRIVATE_CONTEXT_PACKET" \
  --encoder-return "$PRIVATE_ENCODER_RETURN" --output "$FRESH_PRIVATE_WBM_RUN"
python -m hachi.models.illness.pretrained_evidence \
  --snapshot "$PRIVATE_PHASE1_SNAPSHOT" --context-packet "$PRIVATE_CONTEXT_PACKET" \
  --encoder-return "$PRIVATE_ENCODER_RETURN" --run "$PRIVATE_WBM_RUN" --report wbm.json
```

Repeat with `moment_hr` and a distinct fresh private run root. The base-only worker uses `hachi.models.illness.replay`, `--scoring-source` for the exact archived `src`, and `--packets` for the corresponding private run. The comparison assembler revalidates each original packet in an isolated archived worker; newer report code does not bypass source guards or require refitting.
