import json

import pytest

from hachi.evaluation import compare_forecasts
from hachi.models.baselines import BaselineConfig, baseline_factory
from hachi.models.chronos import (
    AdapterLog,
    export_requests,
    load_forecasts,
    paired_quantile_report,
    replay_factory,
    write_requests,
)
from hachi.models.chronos.evaluation import pinball
from hachi.models.chronos.inference import canonical_bytes, forecast_rows, read_requests, write_run

from .conftest import LEVELS, level


def fake_forecaster(contexts, length):
    """Last observed value plus a fixed spread: a stand-in for the GX10 model."""
    output = []
    for context in contexts:
        last = next(v for v in reversed(context) if v is not None)
        output.append([[last + 10 * (q - 0.5) for q in LEVELS] for _ in range(length)])
    return output


def gx10_run(tmp_path, requests_path):
    run = tmp_path / "run"
    run.mkdir()
    requests = read_requests(requests_path)
    rows, _, crossed = forecast_rows(requests, fake_forecaster, batch_size=3, levels=LEVELS)
    write_run(run, requests_path, requests, rows, LEVELS, crossed, {"model": "fake"})
    return run


@pytest.fixture
def exported(tmp_path, manifest, cohort, chronos, evaluation):
    features, _ = cohort
    requests, log, result = export_requests(manifest, features, chronos, evaluation)
    path = tmp_path / "requests.jsonl"
    write_requests(path, requests)
    return path, requests, log, result


def test_export_sees_no_labels_and_writes_each_context_once(exported, manifest):
    path, requests, log, result = exported
    assert result.counts["scored_points"] == 0
    assert (
        result.counts["missing_labels"]
        == result.counts["expected_points"] - result.counts["insufficient_history_points"]
    )
    lines = path.read_text().splitlines()
    assert len(lines) == len(requests) > 0
    assert all(set(json.loads(line)) == {"request_id", "context", "prediction_length"}
               for line in lines)  # fmt: skip
    assert log.counts["requested_origins"] == result.counts["predicted_origins"]
    with pytest.raises(FileExistsError):
        write_requests(path, requests)


def test_replay_pairs_with_a_baseline_on_identical_origins(
    tmp_path, exported, manifest, cohort, chronos, evaluation
):
    path, _, _, exported_result = exported
    features, targets = cohort
    forecasts = load_forecasts(path, gx10_run(tmp_path, path))
    log = AdapterLog()
    result = compare_forecasts(
        manifest,
        features,
        targets,
        baseline_factory(
            BaselineConfig(method="last_valid", metric="heart_rate", aggregation="mean")
        ),
        replay_factory(chronos, forecasts.quantiles, forecasts.levels, log),
        baseline_config=evaluation,
        candidate_config=evaluation,
    )
    assert result.candidate.plan == exported_result.plan
    assert result.summary.counts["paired_points"] > 0
    # The fake model's median is the last value, as is last_valid: identical point errors.
    assert result.summary.difference.mae is not None
    assert result.summary.difference.mae.value == pytest.approx(0.0)
    # Baselines give no interval, so paired targets carry none; Chronos's own run does.
    assert result.summary.candidate_on_paired_targets.interval_coverage is None
    own = result.candidate.metrics
    assert own.interval_coverage is not None and own.mean_interval_width is not None
    assert own.mean_interval_width.value == pytest.approx(8.0)

    report = paired_quantile_report(
        result, targets, log, forecasts.levels, evaluation, manifest.seed
    )
    assert report.paired_points == result.summary.counts["paired_points"]
    # A point forecast's mean decile loss is half its absolute error.
    assert report.baseline is not None and result.summary.baseline_on_paired_targets.mae
    assert report.baseline.value == pytest.approx(
        result.summary.baseline_on_paired_targets.mae.value / 2
    )
    assert report.candidate is not None and report.difference is not None
    assert set(report.calibration) == {"0.50", "0.80", "0.90", "0.98"}


def test_replay_refuses_contexts_the_export_did_not_produce(
    tmp_path, exported, manifest, cohort, chronos, evaluation
):
    path, _, _, _ = exported
    features, targets = cohort
    forecasts = load_forecasts(path, gx10_run(tmp_path, path))
    # A history value changed after export means a different causal context.
    shifted = [f.model_copy(update={"aggregate": f.aggregate.model_copy(
        update={"value": f.value + 1}) }) for f in features]  # fmt: skip
    with pytest.raises(ValueError, match="no GX10 forecast"):
        compare_forecasts(
            manifest,
            shifted,
            targets,
            baseline_factory(
                BaselineConfig(method="last_valid", metric="heart_rate", aggregation="mean")
            ),
            replay_factory(chronos, forecasts.quantiles, forecasts.levels, AdapterLog()),
            baseline_config=evaluation,
            candidate_config=evaluation,
        )


def test_load_forecasts_verifies_both_files(tmp_path, exported):
    path, _, _, _ = exported
    run = gx10_run(tmp_path, path)
    predictions = run / "predictions.jsonl"
    data = predictions.read_bytes()
    predictions.chmod(0o600)
    predictions.write_bytes(data.replace(b"[", b"[ ", 1))
    with pytest.raises(ValueError, match="checksum"):
        load_forecasts(path, run)
    predictions.write_bytes(data)
    other = tmp_path / "other.jsonl"
    other.write_bytes(path.read_bytes() + canonical_bytes({"request_id": "x"}))
    with pytest.raises(ValueError, match="different request file"):
        load_forecasts(other, run)


def test_pinball_is_asymmetric():
    assert pinball(10.0, 8.0, 0.9) == pytest.approx(1.8)
    assert pinball(10.0, 12.0, 0.9) == pytest.approx(0.2)
    assert level("synthetic-1", 4) == 62.0
