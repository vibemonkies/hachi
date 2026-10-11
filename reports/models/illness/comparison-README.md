# Comparison evidence and limits

[comparison.json](comparison.json) contains complete whole-window, common-runtime-context and identical-row paired results across all seven families, three fixed heads and 24/48/72h horizons. [comparison.md](comparison.md) is rendered byte-for-byte from that canonical JSON; reproduction instructions live here separately.

Runtime-supported context denominators include unavailable scoring folds. Representation heads cover 35/84, 49/104 and 64/127 common-context windows at 24/48/72h. Missing rows are not dropped from the denominator or assigned negative labels. Inner1 calibration lacks supported negative outcomes; inner2 validation lacks negatives. Ranking and paired intervals report their estimable bootstrap counts explicitly. Class-degenerate resamples do not establish more independent negative participants; population calibration remains unsupported.

All four actual source-frozen feature/head packets passed full identity/label/predictor/training checks and artifact replay. Each separate base-only replay reloaded 18 artifacts and 816 predictions with zero changed alerts. The comparison also reloaded the three original accepted baseline families: 81 artifacts, 4,464 predictions, maximum difference 6.661338147750939e-16, zero changed alerts, without NumPy or scikit-learn. No tuning, engineering-driven refit, friend case or outer-test evaluation occurred. #13 remains open for accepted comparison evidence, adequate independent negative calibration, final held-out selection and serving proof.

## Reproduce the original packet comparison

Use the committed comparison publisher, authorized private phase1 snapshot/context002, original seven encoder files and the original three Chronos files. The command verifies every pretrained packet in a fresh isolated archive of its exact scoring commit, then replays accepted baseline artifacts in a NumPy/scikit-learn-free environment. It performs no fitting, threshold changes, feature selection or outer-test evaluation. The JSON records actual metric runtime package versions separately from archived lockfile provenance.

```sh
python -m hachi.models.illness.comparison_evidence \
  --snapshot "$PRIVATE_PHASE1_SNAPSHOT" --context-packet "$PRIVATE_CONTEXT_PACKET" \
  --baseline-root "$PRIVATE_ORIGINAL_BASELINE_ROOT" \
  --chronos-inference "$PRIVATE_CHRONOS_RETURN" --encoder-return "$PRIVATE_ENCODER_RETURN" \
  --base-python "$PRIVATE_BASE_ONLY_PYTHON" \
  --run meanpool_hr "$PRIVATE_MEANPOOL_RUN" --run wbm_hr "$PRIVATE_WBM_RUN" \
  --run moment_hr "$PRIVATE_MOMENT_RUN" --run chronos_hr "$PRIVATE_CHRONOS_RUN" \
  --output "$FRESH_PRIVATE_AGGREGATE_OUTPUT"
```

Baseline root contains the three accepted `*-002` directories. Actual feature runs are MeanPool003, WBM001, MOMENT001 and Chronos001. Pretrained scoring revisions are `f15a1686a22c496fb2b8138942b6283acaee8273` (MeanPool/Chronos) and `9e6a108d4719ddccb6ec9dd6f3b6a7ac66477b49` (WBM/MOMENT); original baseline source is `722f51ae1d5bdcdd46dbfa594acff872444839a4`. The publisher preserves original private packets and compares their actual validation scores, with no engineering-driven refits. Hashes of consumed original inputs are captured before validation and checked again before publication. Public report paths contain sanitized aggregates only.
