# Product scope and completion

## Intended experience

A user imports a wearable history, sees which signals are usable, and selects an as-of date. Hachi forecasts the next day, shows changes relative to a personal baseline, and explains which observations support each output. A symptoms flow supports illness and recovery evaluation. A sleep-schedule comparison asks for both bedtime and wake time, displays assumptions, and distinguishes simulation from measured personal prediction.

The primary demo is a real data → trained model → API → interface path, with a replay that reveals future observations only after predictions have been saved. The friend who is currently sick is a late held-out case study, not training data or a substitute for cohort evaluation.

## Exact tasks

| Task | Target | Required evidence | Display before evidence exists |
|---|---|---|---|
| Physiology forecast | Next 24 hourly bins for available signals; separately next completed local day's resting HR, sleep duration, and other supported daily metrics | Held-out errors and interval coverage against last-value and seasonal baselines | Unavailable, or visibly synthetic fixture in development |
| Anomaly monitoring | Causal deviation from personal historical baseline | Healthy-period alert burden, missingness rules, confounder analysis | Anomaly score, never infection probability |
| Illness onset | New symptom onset within 24/48/72 hours after cutoff, for participants without an ongoing episode | Valid onset labels, participant holdout, calibration and false-alert analysis | Unavailable with reason if labels/access are missing |
| Recovery | Time until a prespecified symptom-resolution endpoint, conditional on an ongoing episode | Censoring-aware held-out evaluation and comparison with episode-duration baseline | Unavailable if follow-up cannot establish resolution |
| Alertness | Predicted measured alertness or a conditional sleep-pressure/circadian simulation | Actual rating/PVT labels for personal claims; documented equations and assumptions for simulation | Clearly labeled simulation without a personal accuracy claim |

Do not rename COVID-positive-test prediction as common-cold prediction. A test date is not symptom onset. Do not infer biochemical lab values from a watch without paired labels and a separate validation study. A seven-day illness claim is outside the initial target definition and requires its own evidence.

## Architecture choice

Use a modular Python modeling/backend package, Parquet for versioned analytical data, SQLite for local job/report metadata, FastAPI for the app contract, and React/Vite with TypeScript for the UI. Pin package versions and generate schema types in the foundation issues; this planning commit does not pretend those dependencies have been tested together.

Train task heads on numerical time series and, where useful, pretrained representations. Compare an ensemble against its individual members using validation-only selection. This allows independent model work without mixing incompatible sensor modalities. A language model can later explain structured results, but cannot manufacture probabilities or serve as the medical predictor.

Alternatives considered: one large medical/chat model loses the direct time-series target and makes evaluation harder; a single deep network trained from scratch discards available pretrained representations; merging all public datasets confuses different sensors, populations, and labels. Each admitted dataset instead declares its task and feature compatibility.

## Completion gates

**Research demo ready** requires:

- Reproducible ingestion of a real permitted dataset and an Apple export parser tested with consented data before claiming personal import works.
- At least one actual pretrained-model run and a trained task head or fine-tuning experiment, evaluated against meaningful baselines. If the baseline wins, serve it and show the real comparison.
- A frozen participant/temporal evaluation, a versioned selected artifact, and an app using that exact artifact.
- Working import/status/error paths, data-quality display, forecasts, anomaly timeline, self-report collection, sleep comparison, and honest unavailable states.
- Illness and recovery issues either meet their research acceptance criteria or remain explicitly blocked. A reduced demo may be presented with those limits; it is not completion of the full predictive vision.
- End-to-end rehearsal, a saved replay of real inference, readable setup steps, source attribution, and a presentation with measured results.

**Full initial predictive scope complete** additionally requires labeled illness and recovery evaluations, measured alertness evaluation for any personal alertness claim, and all required roadmap gates satisfied. Closing an issue as rejected, blocked, or out-of-scope does not satisfy a required capability.

**Clinical validation is not a hackathon completion criterion or a claim.** This is a research prototype. The interface must not describe forecasts as diagnoses or provide treatment decisions.

## Presentation story

Show a supported physiological forecast, its actual future outcome, and baseline comparison first. Explain what pretraining contributed. Then show an anomaly replay and the separation between unusual physiology and verified illness. Present the friend case only with permission and an explicit one-person limitation. Close with quantified failures and the next validation experiment.
