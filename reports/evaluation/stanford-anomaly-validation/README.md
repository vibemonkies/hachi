# Observed symptom-free nightly anomaly burden

This completes the real-data burden measurement for #9 alongside the previously
published PMData forecast and pinned upstream NightSignal comparisons. The clean
run used `ea09c7c5b473171695584cabcc4a63fd5b33b08b`, admitted Stanford phase-1 archive
`52ca976e…f4`, and clinical snapshot `168d5413…a33`. Full identities, source hashes,
frozen configuration and saved artifact reference are in `summary.json`.
`acceptance.json` binds the private packet's hash index and canonical manifests.

The full 121-person roster was split before label eligibility: outer4/inner3,
seed42, 60 training/30 validation/31 sealed test people per inner fold, active
outer0. The three inner validation groups are disjoint. Only the nine development
participants with observed negative 24-hour onset windows enter this report;
unlabeled controls and outer-test participants never become healthy examples.
Here "symptom-free" means the locked survey/window definition, not proven absence
of infection or a population sample of healthy time.

| Primary conservative minute-edge policy | Result |
| --- | ---: |
| Observed eligible control days | 134 |
| Scored control days / participants | 29 / 3 |
| Missing-rest abstentions | 99 |
| Cold-start abstentions | 6 |
| Alerted control days / alert episodes | 3 / 2 |
| Participant mean episodes per 30 scored control days | 1.1765 |
| 95% participant bootstrap interval | 0–3.5294 |
| Participant mean alerted fraction of scored days | 0.0588 |
| 95% participant bootstrap interval | 0–0.1765 |

The pooled secondary burden is 0.4478 episodes per 30 **all observed** control days,
including abstentions. It cannot substitute for the scored-day rate or coverage:
only 21.6% of eligible control days scored. Three supported participants give weak
uncertainty estimates. Start-only and end-only step-edge sensitivities have the
same counts and aggregate rates; they do not prove the undocumented source clock
or timestamp semantics are correct.

The frozen algorithm uses standard HR/steps files only, recorded zero-step support,
equal-minute HR medians, midnight–07:00 floating-local nights and next-midnight
decisions. Duplicate identical instants count once; conflicting values remain
unknown. A personal 28-day median/MAD baseline needs seven prior supported nights,
30 quiet HR minutes per night, a 1bpm scale floor and a fixed two-sided threshold3.
Prior survey nights known to be symptomatic are omitted. Exercise, alcohol,
vaccination and travel are unavailable; no absence of confounding is inferred.
No illness probability is produced. Shifted wall-clock dates represented with Z
are storage coordinates, not actual UTC or cross-dataset alignment.

The saved data-only configuration replays all 402 primary/sensitivity control
decisions exactly from their private causal histories. An independent CSV reader
reconciles 72 real resting-median/quiet-coverage checks with zero mismatches, including
measurable and unavailable nights. All 40 indexed private files verify; personal
rows, histories and per-person counts stay in the private packet (0700/0600).
The forecast artifact source receipts remain byte-identical to the PMData packet.

```sh
uv run python -m hachi.models.baselines.stanford.burden \
  --snapshot "$PRIVATE_CLINICAL_SNAPSHOT" \
  --archive "$PRIVATE_STANFORD_ARCHIVE" \
  --output "$NEW_PRIVATE_RUN_ROOT" \
  --protocol configs/experiments/baselines/stanford-burden.json
uv run python scripts/evaluation/stanford_reconcile.py \
  --archive "$PRIVATE_STANFORD_ARCHIVE" --packet "$PRIVATE_RUN_ROOT"
```

The common clinical protocol in `configs/evaluation/stanford-phase1-clinical.json`
fixes this same roster/fold plan for #13/#14 before their task-specific scoring.
Both admitted labels-1 and labels-2 snapshots yield the identical plan; the latter
adds symptom scores. Final illness/recovery modeling, selection and outer-test
evaluation remain separate gates.
