# Frozen MeanPool clinical development control

The actual #11 HR-only MeanPool summary and original CPU heads ran at `f15a1686a22c496fb2b8138942b6283acaee8273`. The frozen comparison remains `937c6765e61663edbb431c73e5a07bc97bf3afaced5e993a689e8efd70e3ecd6`; original task, calibration, burden and uncertainty choices are unchanged. This nonlearned 76-component summary uses the same 168-hour native input as the pretrained encoders, alongside four cutoff-safe survey-history features. No dimensionality search, friend case or outer test was used.

Eighteen fits passed. All nine inner1 fits were unavailable because context-supported calibration contains no negative outcome windows. The scored subset has **17 of 30 eligible validation participants and 19 of 36 incident episodes**, with 91/87/94 windows at 24/48/72h. The JSON exposes the complete eligible denominators, per-fold support gates and scored counts. Missing folds are not imputed or described as a complete comparison.

The committed evidence command rebuilds original request features; validates the complete frozen split, typed run manifest, source bytes and fit/calibration provenance; checks every saved validation label and feature; replays artifacts; and re-derives all metrics and participant uncertainty. [meanpool.json](meanpool.json) contains AUPRC/AUROC, Brier, reliability, PPV/sensitivity, alert episodes, negative-day burden and interval lead time. The independent base-only worker at the archived scoring source reloads 18 artifacts and replays 816 predictions without NumPy or scikit-learn: maximum difference `7.771561172376096e-16`, zero changed decisions. Its aggregate receipt is [meanpool-base-replay.json](meanpool-base-replay.json).

The initial private MeanPool packets remain intact. After report receipt validation and optional dependency fixes, this run's complete metrics and descriptive selection state match the initial run exactly. These are engineering verification repeats under one frozen policy, not additional selection experiments.

High ranking values in this selected illness-survey cohort do **not** establish added physiological information or population calibration. Survey participation already distinguishes many positive and negative windows. Actual whole-window and common-runtime-supported-context paired comparisons with survey/rest/anomaly and all frozen representations are now published in [comparison.json](comparison.json), with unavailable folds explicit and independent acceptance still pending. No candidate is promoted or served. Issue13 stays open for accepted comparison evidence, adequate independent negative calibration and final held-out/serving gates.

## Reproduce

Use the clean archived scoring source `f15a1686a22c496fb2b8138942b6283acaee8273`, locked baselines environment and authorized private snapshot/context packet. Private raw data, fold joins, predictions and models stay outside Git.

```sh
python -m hachi.models.illness.pretrained_run --family meanpool_hr \
  --snapshot "$PRIVATE_PHASE1_SNAPSHOT" --context-packet "$PRIVATE_CONTEXT_PACKET" \
  --output "$FRESH_PRIVATE_MEANPOOL_RUN"
python -m hachi.models.illness.pretrained_evidence \
  --snapshot "$PRIVATE_PHASE1_SNAPSHOT" --context-packet "$PRIVATE_CONTEXT_PACKET" \
  --run "$PRIVATE_MEANPOOL_RUN" --report meanpool.json
```

The base-only replay uses `hachi.models.illness.replay` with `--scoring-source` pointing to `src` extracted from that exact commit and `--packets` pointing to the private CPU run. The shifted floating clock represented as Z is not actual UTC. Retrospective episode/outcome metadata remains labels only; COVID-specific findings are not described as performance for all colds.
