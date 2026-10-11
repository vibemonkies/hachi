import json
import subprocess
import sys
from pathlib import Path

import pytest

from hachi.models.chronos import inference

SCRIPT = Path(inference.__file__)


def row(context, length=2, **override):
    data = {
        "request_id": inference.request_id(context, length),
        "context": context,
        "prediction_length": length,
    }
    return {**data, **override}


@pytest.mark.parametrize("script", [SCRIPT, SCRIPT.with_name("finetune.py")])
def test_scripts_import_only_the_standard_library(script):
    # The pinned GX10 runtime has torch/Chronos but no Hachi data stack.
    probe = (
        "import runpy, sys; runpy.run_path(sys.argv[1]); "
        "bad = {'hachi', 'pydantic', 'pyarrow', 'torch', 'numpy', 'chronos'} & set(sys.modules); "
        "print(sorted(bad))"
    )
    output = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(script)], capture_output=True, text=True, check=True
    )
    assert output.stdout.strip() == "[]"


def test_request_checks_reject_tampering_and_impossible_inputs():
    assert inference.check_request(row([60.0, None, 61.5]))[2] == 2
    with pytest.raises(ValueError, match="does not match"):
        inference.check_request(row([60.0], request_id="0" * 64))
    with pytest.raises(ValueError, match="at least one observed"):
        inference.check_request(row([None, None]))
    with pytest.raises(ValueError, match="finite floats"):
        inference.check_request({**row([60.0]), "context": [60]})
    with pytest.raises(ValueError, match="output limit"):
        inference.check_request(row([60.0], 1025))
    with pytest.raises(ValueError, match="exactly"):
        inference.check_request({**row([60.0]), "subject_id": "synthetic-0"})


def test_duplicate_requests_are_refused(tmp_path):
    path = tmp_path / "requests.jsonl"
    path.write_bytes(inference.canonical_bytes(row([60.0])) * 2)
    with pytest.raises(ValueError, match="duplicate"):
        inference.read_requests(path)


def test_forecast_rows_group_by_horizon_and_count_crossings():
    requests = [
        inference.check_request(row([60.0], 2)),
        inference.check_request(row([61.0], 1)),
        inference.check_request(row([62.0], 2)),
    ]
    calls = []

    def forecaster(contexts, length):
        calls.append((len(contexts), length))
        values = [item.context[0] for item in contexts]
        return [[[v + 1, v] if v == 62.0 else [v, v + 1]] * length for v in values]

    ticks = iter(range(100))
    rows, timings, crossed = inference.forecast_rows(
        requests, forecaster, batch_size=1, levels=(0.1, 0.9), clock=lambda: next(ticks)
    )
    assert calls == [(1, 1), (1, 2), (1, 2)]
    assert [r["request_id"] for r in rows] == [requests[i].request_id for i in (1, 0, 2)]
    assert crossed == 2  # both steps of the crossing series; values are stored unchanged
    assert rows[2]["quantiles"] == [[63.0, 62.0]] * 2
    assert [t["seconds"] for t in timings] == [1, 1, 1]


def test_forecast_rows_reject_wrong_shapes_and_non_finite_values():
    requests = [inference.check_request(row([60.0], 2))]
    with pytest.raises(ValueError, match="shape"):
        inference.forecast_rows(
            requests, lambda c, n: [[[60.0, 61.0]]], batch_size=4, levels=(1, 2)
        )
    with pytest.raises(ValueError, match="non-finite"):
        inference.forecast_rows(
            requests, lambda c, n: [[[60.0, float("nan")]] * 2], batch_size=4, levels=(1, 2)
        )


def test_write_run_never_overwrites(tmp_path):
    requests_path = tmp_path / "requests.jsonl"
    requests_path.write_bytes(inference.canonical_bytes(row([60.0], 1)))
    requests = inference.read_requests(requests_path)
    rows = [{"request_id": requests[0].request_id, "quantiles": [[59.0, 61.0]]}]
    evidence = inference.write_run(tmp_path, requests_path, requests, rows, (0.1, 0.9), 0, {})
    assert evidence["requests"] == 1 and evidence["context_lengths"] == [1]
    assert json.loads((tmp_path / "inference.json").read_text()) == evidence
    with pytest.raises(FileExistsError):
        inference.write_run(tmp_path, requests_path, requests, rows, (0.1, 0.9), 0, {})


def test_past_covariates_are_checked_hashed_and_batched_by_schema():
    plain = row([60.0, 61.0], 2)
    assert plain["request_id"] == inference.request_id([60.0, 61.0], 2, {})
    covariates = {"steps": [10.0, None]}
    with_steps = {
        "request_id": inference.request_id([60.0, 61.0], 2, covariates),
        "context": [60.0, 61.0],
        "prediction_length": 2,
        "past_covariates": covariates,
    }
    assert with_steps["request_id"] != plain["request_id"]
    parsed = inference.check_request(with_steps)
    assert parsed.past_covariates == covariates
    with pytest.raises(ValueError, match="align"):
        inference.check_request(
            {
                **with_steps,
                "past_covariates": {"steps": [1.0]},
                "request_id": inference.request_id([60.0, 61.0], 2, {"steps": [1.0]}),
            }
        )
    with pytest.raises(ValueError, match="nonempty mapping"):
        inference.check_request({**plain, "past_covariates": {}})
    schemas = []

    def forecaster(items, length):
        schemas.append(sorted({tuple(sorted(i.past_covariates)) for i in items}))
        return [[[1.0, 2.0]] * length for _ in items]

    inference.forecast_rows(
        [inference.check_request(plain), parsed], forecaster, batch_size=8, levels=(0.1, 0.9)
    )
    assert schemas == [[()], [("steps",)]]


def test_embed_rows_need_univariate_contexts_and_one_width():
    plain = inference.check_request(row([60.0], 2))
    rows = inference.embed_rows([plain], lambda items: [([0.5, 1.5], 60.0, 1.0)], batch_size=4)
    assert rows == [
        {"request_id": plain.request_id, "embedding": [0.5, 1.5], "loc": 60.0, "scale": 1.0}
    ]
    other = inference.check_request(row([61.0], 2))
    with pytest.raises(ValueError, match="one width"):
        inference.embed_rows(
            [plain, other], lambda items: [([0.5], 1.0, 1.0), ([0.5, 1.0], 1.0, 1.0)], batch_size=4
        )
