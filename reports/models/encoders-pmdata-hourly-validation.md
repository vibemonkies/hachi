# Frozen wearable representations vs handcrafted features: PMData hourly heart rate, validation folds (#11)

This report has aggregate results only: no participant ids, rows, cutoffs or predictions. The machine-readable summary is [`encoders-pmdata-hourly-validation.json`](encoders-pmdata-hourly-validation.json). The GPU runtime, the kernel proofs and every failure met on the way are in [`infra/gx10/encoders/README.md`](../../infra/gx10/encoders/README.md).

**What this is.** It tests whether a frozen pretrained wearable representation adds information beyond the #9 handcrafted features when forecasting next-day hourly mean heart rate on PMData.
- **Representations:** OpenMHC's WBM and MOMENT-1-large as the independent comparator.
- **Head:** one simple trained head, a phase-modulated ridge regression. It is fitted on the handcrafted features alone, on embeddings alone, and on both. Every candidate is paired with the *same head on handcrafted inputs*, on identical origins and targets.
- **Protocol:** the frozen #7/#9 protocol, unchanged, scored on the inner validation folds of outer fold 0.

**What it is not.** It is not a held-out test result: the outer test fold stays sealed. It is not a fine-tuned model, not a reproduction of OpenMHC's own benchmark (the OpenMHC-XS data is gated, see Limitations), and not a claim about Apple Watch data, illness or any population beyond these 12 participants over one week.

## Answer

**No evidence that either frozen representation adds information here.**
- **Frozen WBM.** Adding it to the handcrafted features changes MAE by **+0.22 bpm (−0.46 to +0.96)** and RMSE by **+0.41 (−0.21 to +1.06)**.
- **Frozen MOMENT.** Adding it changes MAE by **+0.53 (−0.08 to +1.08)**.
- **Embeddings alone** are clearly worse than the handcrafted head: WBM +1.78 (+0.55 to +2.96) and MOMENT +2.86 (+1.04 to +4.43) bpm MAE.
- **The head itself.** The shared ridge head on handcrafted inputs beats the #9 tree on the same inputs: the tree is +0.54 (+0.28 to +0.84) bpm MAE worse. That comparison concerns the head, not the representations.

None of this promotes anything. Selection and the sealed test belong to the protocol (#12/#13).

## Identity

| | |
|---|---|
| Code | `issue-11-encoders` at `82febecbfdc070a0c453a663d814a53c3d047655`, clean tree, including main `f08fd01`. |
| Protocol | `configs/evaluation/pmdata-hourly-validation.json`, `document_sha256` `2adbe991611b949f2a99877422e5836f86540f00ee8961db83128ca554134bd7`. Bound by file SHA-256 in `configs/models/encoders/pmdata-encoders.json` (experiment `document_sha256` `257f6e321e9bd26b95aaea2931a3df64f12d8838cb8ad8917abe3f41304c53fc`). |
| Dataset | PMData `simula-2020-04-24`, snapshot `06606ac2708b1c5329b1cfa04e6edfb9a0583c5a6c9f2eb1465b07aebab2ee47`, verified at load. |
| Splits | Nested plan `df6fd2b36daf9514b7e2e1c16eb32de414c65712601371a9e08fc0b17b741c06`; the shared `pmdata_run.load_inputs`/`fold_split`. Outer fold 0's test (4 participants) is sealed; 3 inner folds of 4 validation participants each. |
| WBM | `MyHeartCounts/openmhc-wbm-dp` revision `5db7e4598e1d1da3cdaeb04dce5e9b1ccaf21334`. `model.ckpt` sha256 `0c00e6d9…580d`, loaded with `weights_only=True`. Architecture: OpenMHC `a2d67834` `week_encoders_mamba2.py`/`tokenizers.py`, fetched at run time and hash-checked. mamba-ssm 2.2.4 + causal-conv1d 1.5.0.post8, built for sm_120/sm_121. |
| MOMENT | `AutonLab/MOMENT-1-large` revision `ca58581bc7bea2ebed4e80dc0a3e4b8b609c6ecc`, `model.safetensors` sha256 `a5692805…1572`. momentfm 0.1.5 at `38f7310`. |
| Licenses | **MOMENT:** MIT. **WBM:** conflicting statements. The HF card at the pinned revision says CC BY 4.0, the OpenMHC README says "Models OpenRAIL", and the repo has no LICENSE file. Hachi relies on the CC BY 4.0 grant where the weights are distributed, with attribution (OpenMHC, arXiv 2607.16235; Apple, arXiv 2507.00191). It also applies the stricter reading until the authors resolve the conflict: research evaluation only, no redistribution of the checkpoint or any derived model, no medical-advice use. |
| GPU runtime | GX10 `5ASB`, NVIDIA GB10 (12.1). Encoder env `envs/ea5d6c71db9ca4a6`: torch 2.8.0+cu129, Triton 3.4.0 with the CUDA 12.9.1 ptxas, transformers 4.57.6. Every job ran through `scripts/gx10/gpu-run --owner justin06lee`. |
| CPU runtime | Justin's Mac (macOS 26.6.2, arm64), Python 3.12.13, `uv.lock` sha256 `1b290745…1297`. Run time 386 s, peak RSS 1.5 GB. |
| Inputs → embeddings | `inputs.npz` sha256 `63cb2622…056e` (2,143 windows). WBM embeddings `wbm.npz` `9225279d…3ccc` (job `issue11-embed-wbm-20261011T115907Z`, 35 s). MOMENT embeddings `moment.npz` `9fb75b7a…832b` (job `issue11-embed-moment-20261011T115317Z`, 132 s). All outputs are finite; reruns differ by 0.0. |

## Cross-check against the #9 runner

This run refits the #9 tree inside `compare_forecasts`. Its tree `split.json`, `origins.json` and `evaluation.json` match SnowyFortress's published [`packet-index.json`](../evaluation/pmdata-hourly-validation/packet-index.json) **byte for byte, 9/9** (3 folds × 3 files). Every candidate was paired on exactly the same origins (`origins.json` is identical across every comparison), and all 1,481 labelled, predicted targets are shared. No model predicted a target another abstained on.

## Inputs, exactly as each checkpoint expects

- **Window.** Each window covers the seven local Europe/Oslo calendar days before a local midnight: 168 hours, the alignment WBM was pretrained on.
  - It is computed as of midnight + 16 h, from bins final by then. 16 h covers the longest sleep-log availability lag in the snapshot, 15.8 h.
  - At a cutoff, a head uses the latest window final at or before it, at most 48 h old.
  - A test proves that recomputing from data truncated at the as-of instant gives the identical window.
  - For the 00:00 UTC protocol cutoffs this is the week ending about 25 h earlier. The handcrafted features cover the latest 48 h.
- **WBM** (OpenMHC `_process_example`, reproduced exactly and tested against it): 19 MyHeartCounts channels, laid out as `[(v − mean) / std · present | missing]`, with the checkpoint's own normalization constants (channels 0–6 z-scored, 7–18 identity).
  - **Mapped:** watch steps (hourly sum), watch distance (sum, m), watch heart rate (hourly mean in **beats per second**, OpenMHC's stored unit), `sleep:asleep` and `sleep:inbed`. Sleep is 1 in a recorded segment, 0 in a worn hour without one, and unknown otherwise.
  - **Unsupported, always masked missing:** iPhone steps, distance and flights; active energy; all ten workout types. PMData has no source for them.
  - **Observed share of the 168×19 input:** watch steps and distance 0.874, heart rate 0.872, asleep and in-bed 0.898. Everything else is 0.
- **MOMENT.** Five univariate series (heart rate, steps, distance, asleep, in bed), each with the week in the last 168 of 512 steps: 21 whole 8-hour patches, left padding, `input_mask = 0` on padding and unknown hours. Each channel gives a 1,024-d embedding, and the five are concatenated. Share of windows with at least one fully observed patch per channel: 0.997 / 0.997 / 0.997 / 1.000 / 1.000. A channel without one is zeros.
- **Device shift.** On observed hours, PMData's Fitbit values sit away from WBM's My Heart Counts normalization: steps z mean +0.40 (std 1.67), distance +0.40 (1.79), heart rate −0.27 (1.11). An unshifted cohort would be near 0 and 1.

## Head and selection

Everything is fixed in the committed experiment config before any score:
- **Design:** `[z, z·sin φ, z·cos φ]` ridge, with z the standardized input blocks and φ the target UTC hour. ridge α = 10, equal participant weights, predictions clipped to the training label range.
- **Embedding blocks:** reduced to 16 principal components fitted on training participants' windows only.
- **Training pairs:** the #9 tree's causal pairs (`TrainingPrefix` data only), restricted to origins where every compared embedding exists. Every candidate therefore trains and scores on one support.
- **No selection on these folds.** The validation folds chose no hyperparameter. The k = 4 and k = 32 rows are a prespecified sensitivity ablation, not a choice.

## Results

Equal participant weighting. 95% intervals are participant-level bootstrap (1,000 resamples, seed 42). Units are bpm. 12 validation participants, 84 planned origins, 2,016 target hours.
- 7 origins (168 hours) are excluded for insufficient history; every model shares the exclusion.
- 249 hours have no eligible label.
- Every model scored the same 1,481 targets and abstained on the same 118.

### Each model on its own predictions

| Model | Inputs | MAE | RMSE | Median pinball |
|---|---|---|---|---|
| ridge-handcrafted | #9 handcrafted (8) | **9.78** (8.83 to 10.74) | **13.78** (12.21 to 15.35) | 4.89 |
| ridge-handcrafted-wbm | handcrafted + WBM (16 PCs) | 10.00 (9.09 to 10.83) | 14.19 (12.90 to 15.60) | 5.00 |
| ridge-handcrafted-moment | handcrafted + MOMENT (16 PCs) | 10.31 (9.43 to 11.17) | 14.17 (12.95 to 15.52) | 5.16 |
| ridge-handcrafted-meanpool | handcrafted + MeanPool of the same week (16 PCs) | 10.47 (9.30 to 11.70) | 14.47 (12.79 to 16.13) | 5.24 |
| ridge-wbm | WBM only | 11.57 (10.88 to 12.18) | 15.69 (14.23 to 17.07) | — |
| ridge-moment | MOMENT only | 12.64 (11.30 to 13.95) | 16.33 (14.65 to 17.83) | — |
| causal tree (#9) | #9 handcrafted, tree head | 10.32 (9.38 to 11.30) | 14.39 (12.98 to 15.85) | 5.16 |

### Paired differences (candidate minus ridge-handcrafted; negative favours the candidate)

| Candidate | ΔMAE | ΔRMSE | Per-fold ΔMAE | Participants lower / higher | Per-participant ΔMAE min / median / max |
|---|---|---|---|---|---|
| + WBM | +0.22 (−0.46 to 0.96) | +0.41 (−0.21 to 1.06) | +0.09, −0.51, +1.09 | 7 / 5 | −1.28 / −0.23 / +2.93 |
| + MOMENT | +0.53 (−0.08 to 1.08) | +0.39 (−0.01 to 0.79) | +0.72, +0.23, +0.64 | 3 / 9 | −0.90 / +0.49 / +2.71 |
| + MeanPool (same week, no learned representation) | +0.69 (−0.09 to 1.54) | +0.69 (−0.03 to 1.59) | +1.14, −0.63, +1.56 | 6 / 6 | −0.85 / +0.05 / +3.80 |
| WBM only | +1.78 (0.55 to 2.96) | +1.91 (0.38 to 3.22) | +2.03, +1.00, +2.32 | 2 / 10 | −3.32 / +1.93 / +5.05 |
| MOMENT only | +2.86 (1.04 to 4.43) | +2.56 (0.97 to 3.91) | +3.73, +1.46, +3.39 | 2 / 10 | −4.97 / +3.08 / +7.77 |
| #9 tree (same handcrafted inputs) | +0.54 (0.28 to 0.84) | +0.61 (0.31 to 0.91) | +0.64, +0.79, +0.19 | 2 / 10 | −0.08 / +0.36 / +1.61 |

### Ablations: missing channels, mask semantics, projection size

These are paired against ridge-handcrafted. Embedding drift is measured against the full WBM input on the same 2,143 windows. For scale, the mean distance of a window's embedding from the cohort mean is 0.22 of its norm.

| WBM input variant | ΔMAE | ΔRMSE | Cosine to full (mean / p05) | Relative L2 to full |
|---|---|---|---|---|
| full (primary) | +0.22 (−0.46 to 0.96) | +0.41 (−0.21 to 1.06) | 1 | 0 |
| heart rate only (steps, distance, sleep masked) | +0.44 (−0.22 to 1.21) | +0.78 (0.04 to 1.52) | 0.85 / 0.77 | 0.59 |
| no sleep channels | +0.29 (−0.38 to 0.97) | +0.49 (−0.20 to 1.15) | 0.96 / 0.95 | 0.27 |
| sleep observed only inside records (alternative mask semantics) | +0.14 (−0.40 to 0.80) | +0.41 (−0.08 to 0.95) | 0.99 / 0.98 | 0.14 |
| workout channels observed as 0 instead of missing | +0.35 (−0.40 to 1.14) | +0.43 (−0.32 to 1.23) | 0.80 / 0.71 | 0.62 |
| full, 4 PCs | −0.22 (−0.72 to 0.25) | −0.03 (−0.47 to 0.51) | — | — |
| full, 32 PCs | +0.90 (−0.13 to 2.05) | +1.21 (0.18 to 2.39) | — | — |
| MOMENT, heart rate channel only | +0.10 (−0.42 to 0.61) | +0.01 (−0.41 to 0.45) | — | — |

What this shows:
- **Mask semantics.** WBM is very sensitive to how *unsupported* channels are presented. Declaring the ten absent workout channels observed-zero instead of missing moves every embedding about three times the natural between-window spread, more than dropping steps, distance and sleep together. "Missing" (the primary choice) is the faithful encoding of a source that has no such channel.
- **Downstream.** No WBM input variant gives a reliable gain or loss at the median-error level. Heart rate alone is worse on RMSE.
- **Projection size.** More principal components hurt (32 PCs: RMSE +1.21). The 4-PC point estimate is the only negative ΔMAE, but its interval spans zero. It was not selected and should not be: choosing it here would be selection on validation.

## Negative results and limitations

- **OpenMHC gate still blocked.** The OpenMHC-XS dataset needs a per-user Dataverse request, which was not granted. So WBM could not be checked against OpenMHC's own benchmark numbers, nor on the data it was built for. Its embeddings are tested here only off-distribution: Fitbit, Norway, 16 participants. That is a limit on interpreting a null result, not evidence that WBM is uninformative.
- **Task mismatch.** WBM was pretrained contrastively for per-person, week-level outcome prediction (33 health labels), with a pooled per-user probe. Forecasting the next 24 hourly heart-rate means from a week-old window is a different use. Its 16 PCs explain weekly behaviour, not tomorrow's hourly trajectory.
- **Missing channels and device shift.** PMData supplies 5 of WBM's 19 channels (no iPhone, active energy or workouts). Its steps and heart rate are shifted from My Heart Counts' scale (z +0.40 and −0.27).
- **Small sample.** 12 validation participants, one week (1–7 Jan 2020), 77 predicted origins, wide intervals. Validation-fold evidence only; the outer test is sealed.
- **Frozen only.** No fine-tuning, no per-person pooling and no alternative heads were tried. Those would be new experiments with their own selection, which belongs to #12.
- **Assumed clocks.** PMData clock mapping and historical availability are documented assumptions (#5). The 16 h as-of delay means a cutoff uses a week ending about 25 h before it.
- **Pretraining overlap.** WBM: none known (My Heart Counts iPhone/Apple Watch cohort vs PMData Fitbit). MOMENT: unknown, since the Time-series Pile was not audited for PMData.

## Acceptance evidence (#11)

| Criterion | Evidence |
|---|---|
| Attempt the selected OpenMHC checkpoint with exact channels, normalization, mask semantics, cadence and license provenance | Pinned revision and file hashes, OpenMHC's input builder reproduced and tested, channel map with explicit unsupported channels, unit check (beats/s), the checkpoint's normalization constants, mask ablations, licence record (`configs/models/encoders/wbm.json`, `specs.py`, `test_specs.py`) |
| Prove model-specific kernels on ARM64/GB10, recording actual failures and compatible alternatives | `infra/gx10/encoders/evidence/2026-10-11/`: 5/5 kernel cases vs references, WBM and MOMENT forward/backward/update proofs, and four recorded failures with their replacements (sdists without CUDA sources, missing Python headers, upstream sm_90-only build "no kernel image", Triton ptxas 12.8 vs sm_121a) |
| Compare frozen embeddings plus a simple trained head to the same head on handcrafted features | The tables above. Same ridge head and identical origins, on the shared protocol, outer test sealed |
| MOMENT as an independently evaluated compatible candidate; record any OpenMHC gate still blocked | MOMENT-1-large results above; OpenMHC-XS gate recorded under Limitations |
| Check missing-channel/device-shift effects; retain head/checkpoint/split manifests | Ablation table and device-shift z above. Every packet holds `split.json` and `run.json` (checkpoint source, revision and license); every head artifact is saved and replay-verified |
| Embedding shapes, finite-output checks, held-out head metrics, ablation, reproducible failure logs | WBM 2,143×256 (×5 variants) and MOMENT 2,143×5,120, all finite, deterministic. Held-out-participant metrics and ablations above. Failure logs on the GX10 with summaries in the evidence directory |

## Approved storage

Participant-level data never goes to Git or GitHub.
- **Inputs:** Justin's T7, `/Volumes/T7/Stockpile/hachi.datasets/runs/justin06lee/issue11-inputs-20261011T112237Z/`, mirrored on the GX10 at `~/hachi/runs/justin06lee/issue11-inputs-20261011T112237Z/`.
- **Run packets** (39 comparison packets (13 per inner fold), saved heads, `oof-predictions.parquet` keyed `(outer_fold, inner_fold, subject_id, cutoff_utc, target_start_utc, model)` for #12/#13): `…/issue11-run-20261011T120409Z/` on the T7 and the GX10. `aggregate-summary.json` sha256 `2a014cc8…f666`, `oof-predictions.parquet` `bd131e03…5d16`.
- **Embeddings:** `…/issue11-embeddings-20261011/` (T7) and `~/hachi/runs/justin06lee/issue11-run-20261011T120409Z-embeddings/` (GX10).
- **Model weights:** the owner's HF cache on the GX10 only.
