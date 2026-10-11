import pytest
from pydantic import ValidationError

from hachi.evaluation import TrainingPrefix
from hachi.models.baselines.tree import Branch, Leaf, TreeArtifact, TreeConfig, fit_tree

from .test_forecast import BASE, HOUR, request, row

pytest.importorskip("sklearn", reason="tree fitting requires the optional baselines extra")


def config():
    return TreeConfig(
        metric="heart_rate",
        aggregation="mean",
        lookback_hours=4,
        min_history_hours=2,
        max_lead_hours=1,
        min_samples_leaf=1,
        min_training_examples=4,
        max_depth=3,
    )


def training(extra=()):
    return TrainingPrefix(
        BASE,
        ("train-a",),
        tuple([row("train-a", h, 60.0 + h % 8) for h in range(-32, 0)] + list(extra)),
    )


def test_fitted_tree_roundtrip_matches_sklearn_inference(monkeypatch):
    from sklearn.tree import DecisionTreeRegressor

    from hachi.models.baselines.tree import _features

    captured = []
    original_fit = DecisionTreeRegressor.fit

    def capture(self, *args, **kwargs):
        result = original_fit(self, *args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(DecisionTreeRegressor, "fit", capture)
    fitted = fit_tree(training(), config())
    loaded = TreeArtifact.model_validate_json(fitted.model_dump_json())
    inputs = request([row("held-out", h, 60.0 + h % 8) for h in range(-4, 0)])
    actual = loaded.predict(inputs)
    reference = captured[0].predict(
        [_features(inputs.history, config(), inputs.cutoff, t.start_utc) for t in inputs.targets]
    )
    assert [estimate.median for estimate in actual] == list(reference)
    assert loaded.training_examples > 4 and loaded.model_id == "causal-hourly-tree-v1"


def test_future_training_and_history_do_not_change_frozen_tree_predictions():
    fitted = fit_tree(training(), config())
    future = [row("train-a", 1, 250.0), row("train-a", -1, 250.0, delay=2)]
    changed = fit_tree(training(future), config())
    assert changed.nodes == fitted.nodes and changed.training_examples == fitted.training_examples
    known = [row("held-out", h, 65.0) for h in range(-4, 0)]
    withheld = [row("held-out", 1, 250.0), row("held-out", -1, 250.0, delay=2)]
    assert fitted.predict(request(known + withheld)) == fitted.predict(request(known))
    assert fitted.predict(request()) == (None, None)
    assert fitted.predict(request(known, horizon=3))[-1] is None
    with pytest.raises(ValueError, match="fit cutoff"):
        fitted.predict(request(known, cutoff=BASE - HOUR))


def test_tree_artifact_refuses_cycles_and_matches_float32_feature_comparisons():
    fitted = TreeArtifact(
        config=config(),
        fit_as_of=BASE,
        training_prefix_sha256="a" * 64,
        training_examples=4,
        nodes=(
            Branch(feature=0, threshold=60.00000002, left=1, right=2),
            Leaf(value=70.0),
            Leaf(value=90.0),
        ),
    )
    inputs = request([row("held-out", -2, 60.0), row("held-out", -1, 60.0000001)])
    assert fitted.predict(inputs)[0].median == 70.0
    with pytest.raises(ValidationError, match="forward references"):
        TreeArtifact.model_validate(
            {
                **fitted.model_dump(),
                "nodes": (
                    Branch(feature=0, threshold=60.0, left=0, right=2),
                    Leaf(value=70.0),
                    Leaf(value=90.0),
                ),
            }
        )


def test_tree_training_inclusion_abstains_without_a_fitted_model():
    cold = fit_tree(TrainingPrefix(BASE, ("train-a",), (row("train-a", -1, 60.0),)), config())
    assert cold.nodes == () and cold.training_examples == 0
    assert cold.predict(request()) == (None, None)


def test_derived_hourly_tree_fit_and_saved_inference_match_raw_path(tmp_path):
    from hachi.contracts.tables import Aggregate
    from hachi.evaluation import HourlyFeature
    from hachi.models.baselines import load_artifact, save_artifact

    def derive(source):
        return HourlyFeature(
            aggregate=Aggregate(
                dataset_id=source.dataset_id,
                subject_id=source.subject_id,
                metric=source.metric,
                unit=source.unit,
                resolution="hour",
                interval_start_utc=source.start_utc,
                interval_end_utc=source.start_utc + HOUR,
                local_date=None,
                tz_name="UTC",
                aggregation="mean",
                value=source.value,
                null_reason=None,
                observed_count=1,
                coverage=0.25,
                source_ids=[source.source_id],
                pipeline_version="generated-1",
            ),
            available_at_utc=max(source.available_at_utc, source.start_utc + HOUR),
            availability_rule="generated-bin-end-1",
        )

    raw_training = training()
    derived_training = TrainingPrefix(
        raw_training.fit_as_of,
        raw_training.subjects,
        tuple(derive(r) for r in raw_training.observations),
    )
    raw = fit_tree(raw_training, config())
    derived = fit_tree(derived_training, config())
    assert derived.nodes == raw.nodes and derived.training_examples == raw.training_examples
    history = [row("held-out", h, 60.0 + h % 8) for h in range(-4, 0)]
    inputs = request([derive(r) for r in history])
    reference = save_artifact(tmp_path / "tree", derived, artifact_id="generated-derived-tree")
    loaded = load_artifact(tmp_path / "tree", reference)
    assert loaded.predict(inputs) == raw.predict(request(history))
