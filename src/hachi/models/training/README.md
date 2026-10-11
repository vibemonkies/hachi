# Adapted models, ensembles and selection — issue #12

Everything runs on the frozen PMData protocol (`configs/evaluation/pmdata-hourly-validation.json`). It uses the three inner validation folds of outer fold 0 only; the outer test stays sealed. The result is in [`reports/models/issue12-pmdata-hourly-selection.md`](../../../../reports/models/issue12-pmdata-hourly-selection.md).

## Predeclared before any score

- **`configs/experiments/pmdata-hourly-selection.json`:** `ensemble.selection.SelectionRule`, an incumbent chain in a fixed complexity order.
  - A challenger replaces the incumbent only if all of these hold:
    - paired ΔMAE upper 95% bound < 0;
    - paired Δ decile-loss upper bound < 0;
    - 80% interval coverage in [0.75, 0.85];
    - abstention ≤ incumbent + 5 pp;
    - single-request p95 ≤ 1 s;
    - memory ≤ 4 GiB.
  - Missing evidence fails its gate.
- **`configs/experiments/pmdata-hourly-adaptation.json`:** grids, fine-tuning, the ridge head, intervals, stacking and budgets. It has two amendments:
  - **Amendment 1:** meta learners (stacking weights, point-model residual intervals) are fitted only on grouped meta-folds inside each inner fold's training participants, over 2019-12-25..2020-01-01. Those targets all end by the first held-out cutoff.
  - **Amendment 2:** #11's encoder heads join as reported comparators only.

## Flow

```sh
snapshot=$HACHI_DATA_ROOT/derived/pmdata-features-1-simula-2020-04-24-06606ac2708b
run=$HACHI_DATA_ROOT/runs/justin06lee/issue12-<stamp>
uv run python -I -m hachi.models.training export --snapshot $snapshot --output $run/export
# GX10 (gpu-run, env 8e30ab7405c3087d): inference.py on export/forecast-requests.jsonl,
#   inference.py --mode embed on export/embed-requests.jsonl  -> copy to $run/gx10-{zeroshot,embed}
uv run python -I -m hachi.models.training choose-context --snapshot $snapshot \
  --export $run/export --zeroshot $run/gx10-zeroshot
# GX10: finetune.py per inner fold and learning rate on export/finetune/inner-<k>/ at that context
uv run --extra baselines python -I -m hachi.models.training score --snapshot $snapshot \
  --export $run/export --zeroshot $run/gx10-zeroshot --embed $run/gx10-embed \
  --finetune <rate>:<fold>:<run dir> ... --external-11 <#11 oof-predictions.parquet> --output $run/score
uv run python -I -m hachi.models.training artifact --snapshot $snapshot --export $run/export \
  --zeroshot $run/gx10-zeroshot --score $run/score --selected <selected> --artifact-dir <dir>
# GX10: inference.py on <dir>/reproduce-requests.jsonl (a fresh run), then:
uv run python -I -m hachi.models.training verify-reproduction --snapshot $snapshot \
  --zeroshot $run/gx10-zeroshot --artifact-dir <dir> --fresh <fresh run dir>
```

## Pieces

| Module | What it does |
|---|---|
| `training/pmdata.py` | Loads and binds the configs, builds inner and meta manifests and the bounded context index (`evaluation.context`), and runs the label-free export |
| `training/meta.py` | Amendment-1 grouped meta-folds. The inner fold's validation participants and the outer test are sealed in every meta manifest |
| `training/windows.py` | Training windows and fine-tune series from a `TrainingPrefix`, each context limited to what its own cutoff could see |
| `training/ridge.py` | Per-lead ridge heads on handcrafted, population-only or Chronos-2 embedding features, saved as data-only `RidgeArtifact`s |
| `training/score.py` | Every candidate on identical origins: meta tables, residual intervals, ensembles, harness replay, paired challenges, the selection chain, ablations, costs and packets |
| `training/artifact.py` | Exports the selected Chronos variant, reloads it, re-derives every request and evaluation, and checks a fresh GX10 reproduction |
| `ensemble/selection.py` | The rule and the chain |
| `ensemble/stacking.py` | Prediction tables, decile LP stacking, equal-weight combination, residual intervals, table replay |
| `chronos/finetune.py` | Full fp32 Chronos-2 fine-tuning on the GX10 with best-checkpoint early stopping on a temporal holdout |

## Causality, in brief

- **Labels:** the export passes no labels to the harness.
- **GX10 inputs:** requests carry no subject ids or cutoffs.
- **Longer context and past steps:** these come only from `evaluation.context`. Every origin's last 48 h must equal the harness history, or the run fails.
- **Meta-level fitting:** stacking weights and residual intervals see only meta-fold points of the inner fold's training participants, all known by the first held-out cutoff.
- **Fine-tuning:** it reads only the inner fold's `TrainingPrefix`. Its early-stopping targets lie in the last 168 h of training participants' data.
