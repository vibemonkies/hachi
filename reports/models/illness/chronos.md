# Frozen Chronos clinical development heads

The actual pinned Chronos return contains 147 finite 768-component embeddings plus location and positive scale, from the identity-free 168-hour HR contexts. CPU prevalence/logistic/tree heads ran at `f15a1686a22c496fb2b8138942b6283acaee8273` under frozen comparison `937c6765e61663edbb431c73e5a07bc97bf3afaced5e993a689e8efd70e3ecd6`. Calibration, threshold burden, uncertainty and participant folds were fixed before these feature scores. The four causal survey-history features remain in every head. No outer test or friend case was used.

Eighteen fits passed; nine inner1 fits were unavailable because context-supported calibration has no negative outcome windows. The scored subset includes **17 of 30 eligible validation participants and 19 of 36 incident episodes**, with 91/87/94 scored windows at 24/48/72h. Inner2 has no negative validation windows, so its within-fold ranking metrics are unavailable. Complete eligible denominators, every support gate, ranking/calibration metrics, participant uncertainty, alert episodes and interval lead time appear in [chronos.json](chronos.json).

The strict compiler rebuilds original feature requests and joins, checks complete frozen splits and manifests, validates every saved validation target and predictor, replays the private artifacts and re-derives all metrics. The independent base-only replay uses archived scoring source without NumPy or scikit-learn: **18 artifacts, 816 predictions, maximum probability difference 5.329070518200751e-15, zero changed alert decisions**. Its receipt is [chronos-base-replay.json](chronos-base-replay.json).

The burden cap constrains threshold selection on training-held calibration participants; it is not a guarantee about untouched validation. Chronos logistic heads exceeded one false alert episode per 30 observed negative cutoff days at 48h and 72h validation. Both the observed estimates and participant uncertainty are retained without retuning. Selected-cohort performance does not establish added physiological information or population calibration; survey participation is a strong confound. Same-row comparisons against all original frozen families remain pending. No candidate is promoted or served; #13 stays open for comparison acceptance, independent negative calibration and final held-out/serving gates.

## Reproduce

Use clean archived scoring source `f15a1686a22c496fb2b8138942b6283acaee8273`, the locked baselines environment, authorized phase1 snapshot, context packet002 and the original Chronos return. Keep raw inputs, private joins, predictions and artifacts outside Git.

```sh
python -m hachi.models.illness.pretrained_run --family chronos_hr \
  --snapshot "$PRIVATE_PHASE1_SNAPSHOT" --context-packet "$PRIVATE_CONTEXT_PACKET" \
  --chronos-inference "$PRIVATE_CHRONOS_RETURN" --output "$FRESH_PRIVATE_CHRONOS_RUN"
python -m hachi.models.illness.pretrained_evidence \
  --snapshot "$PRIVATE_PHASE1_SNAPSHOT" --context-packet "$PRIVATE_CONTEXT_PACKET" \
  --chronos-inference "$PRIVATE_CHRONOS_RETURN" \
  --run "$PRIVATE_CHRONOS_RUN" --report chronos.json
```

Base-only replay runs `hachi.models.illness.replay` with `--scoring-source` pointing to the exact archived `src` and `--packets` to the private run. The shifted floating clock represented as Z is not actual UTC. Retrospective episode/outcome fields remain labels only; COVID-specific findings are not performance claims for all colds.
