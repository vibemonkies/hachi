# Frozen wearable encoders (#11)

This package tests whether a pretrained wearable representation adds information beyond the #9 handcrafted features. Both encoders stay frozen. One simple head is trained on handcrafted inputs, on embeddings, and on both, and every candidate is paired with the handcrafted version of the same head. The evaluation uses the shared #7/#9 PMData protocol (`configs/evaluation/pmdata-hourly-validation.json`) unchanged. Only the inner validation folds of outer fold 0 are scored, and the outer test stays sealed.

- **WBM** `MyHeartCounts/openmhc-wbm-dp`: OpenMHC's bidirectional-Mamba2 week encoder. Pin, input contract and license terms are in `configs/models/encoders/wbm.json`.
- **MOMENT-1-large** `AutonLab/MOMENT-1-large`: the independently evaluated comparator. Pin in `configs/models/encoders/moment.json`.
- **GPU runtime:** the build, the kernel and model proofs, and the failures met on the way are in `infra/gx10/encoders/README.md`.

## Pipeline

```sh
snapshot=/Volumes/T7/Stockpile/hachi.datasets/derived/pmdata-features-1-simula-2020-04-24-06606ac2708b
private=/Volumes/T7/Stockpile/hachi.datasets/runs/justin06lee   # approved private storage
# 1. Mac: causal week windows -> model-ready arrays (private) + sanitized input audit.
uv run --extra baselines python -m hachi.models.encoders.inputs --snapshot $snapshot \
  --experiment configs/models/encoders/pmdata-encoders.json \
  --wbm-config configs/models/encoders/wbm.json --output $private/issue11-inputs-<ts>
# 2. GX10, through scripts/gx10/gpu-run in envs/ea5d6c71db9ca4a6: frozen embeddings (private).
$py src/hachi/models/encoders/gx10/embed.py wbm    --config configs/models/encoders/wbm.json    --inputs inputs.npz --output wbm.npz
$py src/hachi/models/encoders/gx10/embed.py moment --config configs/models/encoders/moment.json --inputs inputs.npz --output moment.npz
# 3. Mac: paired evaluation on the shared protocol; packets, heads and OOF predictions (private).
uv run --extra baselines python -m hachi.models.encoders.run --snapshot $snapshot \
  --experiment configs/models/encoders/pmdata-encoders.json --inputs .../inputs.npz \
  --embeddings .../wbm.npz --embeddings .../moment.npz --output $private/issue11-run-<ts>
# 4. Sanitized aggregate report.
uv run --extra baselines python -m hachi.models.encoders.report --run $private/issue11-run-<ts> \
  --inputs-audit .../input-audit.json --embeddings .../wbm.npz \
  --evidence infra/gx10/encoders/evidence/2026-10-11 \
  --packet-index reports/evaluation/pmdata-hourly-validation/packet-index.json \
  --output reports/models/encoders-pmdata-hourly-validation.json
```

## Inputs and causality (`windows.py`, `specs.py`)

- **Window.** A window is the seven local (Europe/Oslo) calendar days before a local midnight `m`: 168 hours, the alignment WBM was pretrained on.
  - It is computed as of `m + 16 h` from bins that had ended and were final by then. The 16 h covers the longest sleep-log availability lag in this snapshot (15.8 h).
  - A bin that existed but was not final yet is unknown, never zero.
- **Lookup.** At cutoff `c`, a head uses the latest window whose as-of instant is at or before `c`, at most 48 h old. Recomputing from a snapshot truncated at `c` gives the same window; `test_windows.py` proves this.
- **History.** The encoders see more history than the protocol's 48 h lookback, and more channels: steps, distance and sleep. That extra information is the point of the experiment. The `meanpool` candidate (OpenMHC's MeanPool on the same week) separates "more input" from "a learned representation".
- **WBM channels.** Fitbit Versa 2 data maps onto WBM's watch channels:
  - steps → `hk_watch:StepCount` (hourly sum);
  - distance → `hk_watch:DistanceWalkingRunning` (sum, m);
  - heart rate → `hk_watch:HeartRate` (hourly mean, **beats per second**, as OpenMHC stores it);
  - asleep / in bed → `sleep:asleep` / `sleep:inbed`: 1 in a recorded segment, 0 in a worn hour without one, unknown otherwise.
- **Unsupported WBM channels** are always masked missing: the three iPhone channels, active energy and all ten workout types. PMData has no such source.
- **WBM input.** It is OpenMHC's own `[(v − mean) / std · present | missing]`, with the checkpoint's normalization constants.
- **Ablations.** `hr_only`, `no_sleep`, `sleep_records_only` (the alternative mask semantics) and `workouts_zero` change only their channels.
- **MOMENT input.** Each native channel is a univariate 512-step series: the week sits in the last 168 steps (21 whole 8-hour patches), left-padded, with `input_mask = 0` for padding and unknown hours. Per-channel 1,024-d embeddings are concatenated.

## Head (`head.py`)

The head is phase-modulated ridge regression: `[z, z·sin φ, z·cos φ]`, where `z` holds the standardized input blocks and φ is the target's UTC hour.
- **Weighting.** Equal participant weight. `ridge_alpha` and `pca_components` are fixed in the experiment config before any score (10 and 16), so validation folds select nothing.
- **Blocks.** Embedding blocks are projected onto 16 principal components, fitted only on training participants' windows final by the fit cutoff.
- **Training pairs.** They are exactly the #9 tree's causal pairs, from `TrainingPrefix` data only. They are restricted to origins where every compared embedding exists, so all candidates train and score on one support.
- **Predictions** are clipped to the training label range.
- **Artifacts.** Heads are data-only JSON. Each saved head is reloaded, and its replayed predictions must match.

## Outputs (all private except the report)

- One comparison packet per candidate and inner fold. The candidates are every ridge variant and the #9 tree, each against `ridge-handcrafted`. `tree` packets reproduce the published #9 packet index byte for byte.
- `oof-predictions.parquet`, keyed `(outer_fold, inner_fold, subject_id, cutoff_utc, target_start_utc, model)`, for #12/#13.
- Embedding tables: `wbm.npz` and `moment.npz`, keyed by subject and as-of. On the GX10 they live under `~/hachi/runs/justin06lee/issue11-embed-*`.
