# Chronos-2 zero-shot forecasts — issue #10

Zero-shot [`amazon/chronos-2`](https://huggingface.co/amazon/chronos-2) at the #1-pinned
revision, scored by the #7 harness against the #9 comparators on the frozen PMData
validation protocol. The real-data result is in
[`reports/models/chronos-2-pmdata-hourly-validation.md`](../../../../reports/models/chronos-2-pmdata-hourly-validation.md).

## Why the run is split in three

The pinned GX10 runtime (`infra/gx10/requirements.lock`, id `8e30ab7405c3087d`) holds
torch and Chronos but not Hachi's data stack, so `hachi` cannot import there. Rather
than re-resolve that lock, the CPU harness runs twice around one GX10 job:

1. **export** (CPU): `evaluate_forecast` runs with no labels at all. A recording
   predictor turns each `ForecastInput` into a 48 h hourly context ending at the
   cutoff, with absent hours as `null`. The context goes to `requests.jsonl`, keyed
   by its content hash. A request carries no subject id, cutoff or target.
2. **infer** (GX10): `inference.py` checks every request id and the checkpoint's
   weight sha256, then writes all 21 model quantiles per request. It also records
   latency and peak memory. It imports only the standard library at module level,
   and a test enforces that.
3. **score** (CPU): the replay predictor rebuilds each context from the harness's
   `ForecastInput` and looks up its forecast by hash. A context the export did not
   produce has no forecast, so the run fails rather than scoring it.
   `compare_forecasts` then pairs Chronos with each comparator, refit on identical
   origins.

## Adapter rules

- Input: derived `HourlyFeature` bins of the configured metric only. Raw observations,
  other metrics and any covariates raise `UnsupportedInput`. They are refused, not
  silently dropped. `covariates` is fixed to `"none"`, so measured physiology can
  never enter as a known future covariate.
- Limits: the context is at most 8192 h (model limit) and exactly the protocol
  lookback. The horizon is at most 1024 steps. Cutoffs and targets must be whole
  UTC hours. Rows not available by the cutoff are refused.
- Output: median = q0.5, interval = q0.1–q0.9 (nominal 80%). Crossing quantiles are
  rearranged (sorted), which never increases quantile loss. Values outside the
  metric's registered bounds are clipped. Both are counted.

## Commands

```sh
snapshot=$HACHI_DATA_ROOT/derived/pmdata-features-1-simula-2020-04-24-06606ac2708b
run=$HACHI_DATA_ROOT/runs/justin06lee/issue10-<stamp>
common="--snapshot $snapshot --protocol configs/evaluation/pmdata-hourly-validation.json \
  --config configs/models/chronos/pmdata-hourly-hr.json"
uv run python -I -m hachi.models.chronos export $common --output $run/export

# On the GX10, from a clone of the same commit (scripts/gx10/gpu-run sets HACHI_RUN_DIR):
scripts/gx10/gpu-run --owner justin06lee --run-id issue10-<stamp>-infer -- \
  ~/hachi/workspaces/justin06lee/envs/8e30ab7405c3087d/bin/python -I \
  src/hachi/models/chronos/inference.py --requests <requests.jsonl> --model infra/gx10/model.json

# Copy the GX10 run directory back to $run/gx10, then:
uv run python -I -m hachi.models.chronos score $common \
  --export $run/export --gx10-run $run/gx10 --output $run/score
```

The `score/` packets carry per-participant predictions and metrics and stay in
approved storage. Its `aggregate-summary.json` holds no participant identifiers.
`configs/models/chronos/pmdata-hourly-hr.json` is bound to the protocol document by
`protocol_sha256`, so a changed protocol refuses to run.
