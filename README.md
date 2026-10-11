# Hachi

Personal physiological forecasting from wearable history, with measured uncertainty and traceable evidence.

**Status: build plan, collaboration setup and shared contracts v0.1. No Hachi model has been trained, no app is implemented, and no predictive accuracy has been established.**

## Start here

1. Read [which issues can run together and when to push/pull](docs/COORDINATION.md), then the [product scope](docs/PRODUCT.md) and [team roadmap](docs/ROADMAP.md).
2. Pick your first assigned [GitHub issue](https://github.com/vibemonkies/hachi/issues). Check its dependencies before starting.
3. Use the [shared contracts](docs/CONTRACTS.md), [research catalog](docs/RESEARCH.md), and [GX10 workflow](docs/DEVELOPMENT.md).
4. Open a small PR with the issue number and reproducible evidence. Use the [evaluation protocol](docs/EVALUATION.md) for model work.

| Lane | Initial owner | Owns |
|---|---|---|
| Models and evaluation | @ezzy1630 | GX10 model runtime, baselines, pretrained adapters, training, evaluation |
| Data and backend | @justin06lee | Dataset access, ingestion, feature contracts, API, artifact loading |
| Product and demo | @CoffeeCoder1015 | Web app, self-report flows, scenario UI, integration walkthrough, presentation |

These are starting assignments, not statements about anyone's expertise. Reassign issues explicitly when swapping work.

## What we are building

- Forecast next-day physiological measurements from past observations.
- Detect departures from a person's baseline; separately evaluate whether labeled data supports short-horizon illness-onset probabilities.
- Estimate recovery trajectories using symptom history and appropriately labeled episodes.
- Compare sleep schedules through an explicitly conditional alertness model, then calibrate against actual ratings or vigilance measurements.
- Show the data, missingness, model version, forecast intervals, and measured limitations in a working app.

Pretrained models are candidates, not automatic improvements. The training path compares simple baselines, Chronos-2, wearable representations, and learned task heads. A selected model must earn its place on held-out data. See [model selection](docs/RESEARCH.md#model-candidates).

## Repository boundaries

```text
docs/                   shared plan, contracts, evidence requirements
.github/                issue and PR templates, CI
src/hachi/contracts/    authoritative contract models (Justin; reviewed by both callers)
contracts/              generated JSON Schema, TypeScript types, synthetic fixtures
src/hachi/data/         dataset registry now; ingestion and harmonization next (Justin)
configs/datasets/       dataset admission registry: terms, access, checksums (Justin)
tests/                  Python tests
# Planned implementation ownership (created by the corresponding issues):
src/hachi/api/          API and local persistence (Justin)
src/hachi/models/       model adapters and training (Ezzy)
src/hachi/evaluation/   splits, replay, metrics (Ezzy)
apps/web/               product UI (CoffeeCoder)
configs/                versioned experiment and feature definitions
reports/                reviewed, aggregate-only experiment reports
```

## Development

Install [uv](https://docs.astral.sh/uv/) and [bun](https://bun.sh/), then run `make`. It installs the locked environments, regenerates the contracts and runs every check CI runs. `make build` regenerates the JSON Schema, TypeScript types and fixtures after a contract change; `make check` runs lint, tests and the generated-file checks. See the [development workflow](docs/DEVELOPMENT.md#local-toolchain).

Raw exports, participant-level tables, credentials, checkpoints, and private run artifacts stay outside Git. This is a private repository, but repository privacy is not permission to copy another person's health data into it.

Completion is defined by the [demo gate](docs/PRODUCT.md#completion-gates), not the number of closed issues. A blocked dataset or unsupported medical claim remains visible; it is not converted into a successful result.
