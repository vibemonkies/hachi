# Phase1 frozen context availability

The committed pre-score audit at `fcfe9bb` reproduces the nine aggregate fold/horizon records in `context-support.json` from the verified private context packet. It reads only outer0 development participants. It runs no model inference, fitting or prediction scoring. Its support definition is **hourly context coverage only**, an upper bound until actual runtime vector support flags arrive.

| Inner fold | Context contributors fit/calibration/validation | Supported calibration negative windows 24/48/72h | Supported validation ranking |
| --- | --- | --- | --- |
| 0 | 18 / 5 / 7 | 9 / 6 / 3 | Both classes present |
| 1 | 11 / 6 / 13 | 0 / 0 / 0 | Both classes present; fitting unavailable |
| 2 | 15 / 5 / 10 | 9 / 6 / 3 | All positive at each horizon; AUPRC/AUROC unavailable within fold |

The frozen comparison requires at least four context-supported participants **and both outcome classes separately in fit and calibration**. Inner1 therefore remains unavailable at every horizon, even if all its context requests return valid vectors. No negative labels, calibration examples or class gates are imputed or relaxed. Runtime support flags may further reduce coverage in any fold.

The local Chronos feature loader verifies the admitted context packet, exact request/output hashes, pinned public model/weight bytes and extraction script, actual 768-component embeddings and location/scale in bpm. It repeats each identity-free request only through the private fold joins. Every missing or unsupported cutoff receives an explicit null point, preventing an older vector from carrying into it. CPU heads require the frozen feature order and support gate before fitting; preprocessing and calibration remain participant separated. They are descriptive development comparisons with no final winner selection or product probability.

## Reproduction

Use the report-producing implementation `fcfe9bb` in an isolated clean checkout with Hachi's locked baselines environment. Substitute the authorized private snapshot and packet paths below; keep both private. The packet is `illness-clinical-contexts-002` with the canonical context SHA `ca00446cc83ce84f2343b05730f0e06dc859ab3c2806264dbe702de63638a7d6`. The comparison SHA is `937c6765e61663edbb431c73e5a07bc97bf3afaced5e993a689e8efd70e3ecd6`.

```sh
python -m hachi.models.illness.support_audit \
  --snapshot "$PRIVATE_PHASE1_SNAPSHOT" \
  --packet "$PRIVATE_CONTEXT_PACKET" \
  --report context-support.json
```

For a future returned Chronos embed packet, the local CPU command is:

```sh
python -m hachi.models.illness.pretrained_run \
  --snapshot "$PRIVATE_PHASE1_SNAPSHOT" \
  --context-packet "$PRIVATE_CONTEXT_PACKET" \
  --chronos-inference "$PRIVATE_CHRONOS_EMBED_PACKET" \
  --output "$FRESH_PRIVATE_CPU_RUN"
```

No clinical feature scores have run for this report. Parent verified the four identity-free request/policy files on the authorized GX10; joins and labels stayed local. Actual queued pretrained outputs, whole-window/common-supported-context paired evidence, adequate independent negative calibration and final held-out/serving acceptance remain gates. **Issue13 stays open.** The shifted floating clock represented as Z is not actual UTC; retrospective illness metadata remains labels only. These selected illness-survey observations do not establish population calibration or performance for all colds.
