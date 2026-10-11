import pytest

np = pytest.importorskip("numpy", reason="the encoder head requires the optional baselines extra")

from hachi.contracts.base import SCHEMA_VERSION, DatasetSnapshotRef  # noqa: E402
from hachi.contracts.manifests import SplitManifest, TimeWindow  # noqa: E402
from hachi.contracts.tables import Aggregate  # noqa: E402
from hachi.evaluation import (  # noqa: E402
    EvaluationConfig,
    TrainingPrefix,
    compare_forecasts,
    partition_participants,
)
from hachi.models.baselines.tree import TreeConfig, _features  # noqa: E402
from hachi.models.encoders.head import (  # noqa: E402
    EmbeddingTable,
    HeadConfig,
    RidgeHeadArtifact,
    fit_ridge_head,
    ridge_head_factory,
    training_pairs,
)

from .helpers import BASE, HOUR, request, row  # noqa: E402

TREE = TreeConfig(
    metric="heart_rate",
    aggregation="mean",
    lookback_hours=4,
    min_history_hours=2,
    max_lead_hours=1,
    min_samples_leaf=1,
    min_training_examples=4,
)
HEAD = HeadConfig(tree=TREE, ridge_alpha=1.0, pca_components=2, max_staleness_hours=12)
SUBJECTS = ("train-a", "train-b", "held-out")


def series(subject, hours, offset=0.0):
    return [row(subject, h, 60.0 + offset + (h % 8) + (h % 24 > 12)) for h in hours]


def table(name="emb", shift=None):
    """Windows every 6 hours; vector[0] tracks the subject, the rest is seeded noise."""
    rng = np.random.default_rng(7)
    subjects, as_of, vectors = [], [], []
    for i, subject in enumerate(SUBJECTS):
        for k in range(-10, 6):
            subjects.append(subject)
            as_of.append(BASE + k * 6 * HOUR)
            vectors.append([float(i), *rng.normal(size=4)])
    vectors = np.asarray(vectors)
    if shift is not None:
        vectors[[a > shift for a in as_of]] += 100.0
    return EmbeddingTable.from_arrays(name, subjects, as_of, vectors)


def prefix():
    observations = series("train-a", range(-48, 0)) + series("train-b", range(-48, 0), 5.0)
    return TrainingPrefix(BASE, ("train-a", "train-b"), tuple(observations))


def fitted(blocks=("handcrafted", "emb"), tables=None):
    tables = tables or {"emb": table()}
    return fit_ridge_head(
        prefix(), HEAD, model_id="test-head", blocks=blocks, support=("emb",), tables=tables
    )


def test_lookup_uses_the_latest_window_final_by_the_cutoff_within_staleness():
    t = table()
    index = t.lookup("train-a", BASE + 5 * HOUR, 12)
    assert t.as_of_utc[index] == BASE
    assert t.as_of_utc[t.lookup("train-a", BASE + 6 * HOUR, 12)] == BASE + 6 * HOUR
    assert t.lookup("train-a", BASE - 61 * HOUR, 12) is None  # before the first window
    assert t.lookup("train-a", BASE + 60 * HOUR, 12) is None  # stale
    assert t.lookup("nobody", BASE, 12) is None


def test_training_pairs_are_the_tree_features_at_each_causal_origin():
    pairs = training_pairs(prefix(), TREE)
    rows = sorted(prefix().observations, key=lambda r: r.start_utc)
    i = 37
    origin, subject = pairs.origins[i], pairs.subjects[i]
    history = [r for r in rows if r.subject_id == subject and r.start_utc < origin]
    expected = _features(history, TREE, origin, origin)
    assert tuple(pairs.handcrafted[i][:5]) == expected[:5]
    assert all(t < BASE for t in pairs.targets) and all(
        o <= t for o, t in zip(pairs.origins, pairs.targets, strict=True)
    )


def test_head_predicts_finite_bounded_values_and_abstains_without_support():
    head = fitted()
    predict = head.predictor({"emb": table()})
    out = predict(request(series("held-out", range(-4, 0))))
    assert all(e is not None and head.label_min <= e.median <= head.label_max for e in out)
    history = [
        r.model_copy(update={"subject_id": "nobody"}) for r in series("held-out", range(-4, 0))
    ]
    stranger = request(history, subject="nobody")
    assert predict(stranger) == (None, None)


def test_future_windows_change_neither_the_fit_nor_predictions():
    base = fitted()
    leaky = {"emb": table(shift=BASE)}
    changed = fitted(tables=leaky)
    assert changed.coefficients == base.coefficients and changed.projections == base.projections
    history = series("held-out", range(-4, 0))
    assert base.predictor({"emb": table()})(request(history)) == changed.predictor(leaky)(
        request(history)
    )


def test_saved_head_replays_identically_and_refuses_other_tables():
    head = fitted()
    loaded = RidgeHeadArtifact.model_validate_json(head.model_dump_json())
    history = series("held-out", range(-4, 0))
    assert loaded.predictor({"emb": table()})(request(history)) == head.predictor({"emb": table()})(
        request(history)
    )
    with pytest.raises(ValueError, match="differs"):
        loaded.predictor({"emb": table(shift=BASE - 100 * HOUR)})


def test_same_head_on_handcrafted_and_embedding_inputs_pairs_on_identical_origins():
    subjects = [f"s{i}" for i in range(6)]
    parts = partition_participants(subjects, seed=42, validation_count=2, test_count=2)
    manifest = SplitManifest(
        schema_version=SCHEMA_VERSION,
        manifest_id="synthetic-encoder-split",
        created_at_utc=BASE,
        dataset_snapshot=DatasetSnapshotRef(
            dataset_id="synthetic", dataset_version="synthetic-1", snapshot_sha256="a" * 64
        ),
        task="physiology_forecast",
        fold=None,
        n_folds=None,
        **parts,
        lookback_hours=4,
        horizon_hours=2,
        embargo_hours=0,
        cutoff_stride_hours=2,
        min_history_hours=2,
        evaluation_window=TimeWindow(start_utc=BASE, end_utc=BASE + 6 * HOUR),
        seed=42,
        test_opened_at_utc=None,
    )
    observations = [r for i, s in enumerate(subjects) for r in series(s, range(-48, 6), i)]
    labels = [
        Aggregate(
            dataset_id="synthetic",
            subject_id=s,
            metric="heart_rate",
            unit="bpm",
            resolution="hour",
            interval_start_utc=BASE + h * HOUR,
            interval_end_utc=BASE + (h + 1) * HOUR,
            local_date=None,
            tz_name="UTC",
            aggregation="mean",
            value=61.0 + i,
            null_reason=None,
            observed_count=1,
            coverage=1.0,
            source_ids=["generated"],
            pipeline_version="synthetic-1",
        )
        for i, s in enumerate(subjects)
        for h in range(6)
    ]
    rng = np.random.default_rng(3)
    keys = [(s, BASE + k * 6 * HOUR) for s in subjects for k in range(-10, 2)]
    emb = EmbeddingTable.from_arrays(
        "emb", [k[0] for k in keys], [k[1] for k in keys], rng.normal(size=(len(keys), 5))
    )
    config = EvaluationConfig(
        data_mode="synthetic",
        metric="heart_rate",
        aggregation="mean",
        history_policy="causal_prefix",
        pretrained_cohort_overlap="not_applicable",
        overlap_note="Synthetic.",
        bootstrap_samples=50,
        confidence=0.9,
    )

    def factory(blocks):
        return ridge_head_factory(
            HEAD, model_id="h", blocks=blocks, support=("emb",), tables={"emb": emb}, pairs_cache={}
        )

    result = compare_forecasts(
        manifest,
        observations,
        labels,
        factory(("handcrafted",)),
        factory(("handcrafted", "emb")),
        baseline_config=config,
        candidate_config=config,
    )
    counts = result.summary.counts
    assert counts["paired_points"] > 0
    assert counts["baseline_only_points"] == counts["candidate_only_points"] == 0
    assert result.baseline.plan == result.candidate.plan
