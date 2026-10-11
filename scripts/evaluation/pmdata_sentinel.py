"""Real-input causal sentinel: change future and outer-test values, then refit/replay."""

import argparse
import json
from datetime import timedelta
from pathlib import Path

from hachi.evaluation.forecast import evaluate_forecast
from hachi.evaluation.pmdata_run import PMDataProtocol, fold_split, load_inputs
from hachi.evaluation.serialization import document_sha256
from hachi.models.baselines import TreeConfig, fit_baseline, fit_tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    args = parser.parse_args()
    protocol = PMDataProtocol.model_validate_json(args.protocol.read_bytes())
    plan, view, labels = load_inputs(args.snapshot, protocol)
    checks = []
    for fold in plan.folds:
        if fold.outer_fold != protocol.active_outer_fold:
            continue
        split = fold_split(protocol, fold)
        split = split.model_copy(
            update={
                "evaluation_window": split.evaluation_window.model_copy(
                    update={"end_utc": split.evaluation_window.start_utc + timedelta(hours=24)}
                )
            }
        )
        cutoff = split.evaluation_window.start_utc
        mutated = tuple(
            row.model_copy(update={"aggregate": row.aggregate.model_copy(update={"value": 299.0})})
            if row.end_utc > cutoff
            or row.available_at_utc > cutoff
            or row.subject_id in fold.test_subjects
            else row
            for row in view.features
        )
        for config in [*protocol.baselines, protocol.tree]:
            fitted = []

            def factory(training, config=config, fitted=fitted):
                model = (
                    fit_tree(training, config)
                    if isinstance(config, TreeConfig)
                    else fit_baseline(training, config)
                )
                fitted.append(document_sha256(model))
                return model.predict

            before = evaluate_forecast(split, view.features, labels, factory, protocol.evaluation)
            after = evaluate_forecast(split, mutated, labels, factory, protocol.evaluation)
            if (
                fitted[0] != fitted[1]
                or before.predictions != after.predictions
                or before.counts != after.counts
            ):
                raise RuntimeError(
                    "future/test values changed the causal training or earlier predictions"
                )
            checks.append(
                {
                    "outer": fold.outer_fold,
                    "inner": fold.inner_fold,
                    "model": config.method if hasattr(config, "method") else "tree",
                    "mutated_input_bins": sum(
                        a != b for a, b in zip(view.features, mutated, strict=True)
                    ),
                    "planned_origins": before.counts["planned_origins"],
                    "fitted_state_identical": True,
                    "predictions_and_counts_identical": True,
                }
            )
    print(
        json.dumps(
            {
                "data_mode": "real_input_sentinel",
                "protocol_sha256": document_sha256(protocol),
                "outer_test_sealed": True,
                "checks": checks,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
