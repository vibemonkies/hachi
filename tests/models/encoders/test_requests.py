import json

import pytest

np = pytest.importorskip("numpy", reason="encoder inputs require the optional baselines extra")

from hachi.evaluation.serialization import document_sha256  # noqa: E402
from hachi.models.encoders.requests import (  # noqa: E402
    feature_table,
    join_features,
    model_inputs,
    moment_patch_support,
    read_requests,
)

MEANS = np.zeros(19, dtype=np.float32)
STDS = np.ones(19, dtype=np.float32)


def request(hr, steps=None, **overrides):
    record = {
        "context_policy_sha256": "a" * 64,
        "hours": 168,
        "first_hour_local": 0,
        "channels": {"heart_rate": hr} | ({"steps": steps} if steps is not None else {}),
        "units": {"heart_rate": "bpm"} | ({"steps": "count"} if steps is not None else {}),
    } | overrides
    return {**record, "request_sha256": document_sha256(record)}


def write(tmp_path, records):
    path = tmp_path / "contexts.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_requests_map_to_wbm_hr_and_steps_with_everything_else_missing(tmp_path):
    hr = [60.0 + h % 24 for h in range(168)]
    hr[5] = None
    steps = [float(10 * (h % 24)) for h in range(168)]
    hashes, values, policy = read_requests(write(tmp_path, [request(hr, steps), request(hr)]))
    assert len(hashes) == 2 and policy == "a" * 64
    arrays = model_inputs(values, MEANS, STDS)
    x = arrays["wbm_hr_steps"]
    assert x.shape == (2, 168, 38)
    assert x[0, 0, 5] == pytest.approx(60.0 / 60.0) and x[0, 5, 19 + 5] == 1.0  # beats/s; null hour
    assert x[0, 1, 3] == 10.0 and x[1, :, 19 + 3].all()  # steps observed only where supplied
    missing = [c for c in range(19) if c not in (3, 5)]
    assert x[:, :, [19 + c for c in missing]].all()  # distance, sleep, iPhone, energy, workouts
    assert arrays["wbm_hr"][:, :, 19 + 3].all()  # HR-only masks steps even when supplied
    assert arrays["moment_x"].shape == (2, 2, 512) and not arrays["moment_mask"][1, 1].any()
    assert arrays["meanpool_hr"].shape == (2, 76)
    assert list(arrays["moment_channels"]) == ["heart_rate", "steps"]


def test_hr_only_exports_get_no_steps_variants(tmp_path):
    _, values, _ = read_requests(write(tmp_path, [request([65.0] * 168)]))
    arrays = model_inputs(values, MEANS, STDS)
    assert set(arrays) == {"wbm_hr", "meanpool_hr", "moment_x", "moment_mask", "moment_channels"}
    assert arrays["moment_x"].shape == (1, 1, 512)


def test_requests_are_refused_when_hash_alignment_or_values_are_wrong(tmp_path):
    hr = [70.0] * 168
    tampered = request(hr)
    tampered["channels"]["heart_rate"][0] = 71.0
    for bad in (
        tampered,
        request(hr, first_hour_local=6),
        request([70.0] * 100),
        request([400.0] * 168),
        request(hr, units={"heart_rate": "Hz"}),
    ):
        with pytest.raises(ValueError):
            read_requests(write(tmp_path, [bad]))
    with pytest.raises(ValueError, match="duplicate"):
        read_requests(write(tmp_path, [request(hr), request(hr)]))


def test_feature_table_keys_vectors_by_request_hash():
    hashes = np.asarray(["h1", "h2"])
    table = feature_table(
        hashes, {"wbm_hr": np.ones((2, 256)), "moment_hr": np.zeros((2, 1024))}, {"k": "v"}
    )
    rows = table.to_pylist()
    assert table.num_rows == 4 and {r["model"] for r in rows} == {"wbm_hr", "moment_hr"}
    assert {r["dim"] for r in rows} == {256, 1024} and all(r["finite"] for r in rows)
    assert table.schema.metadata[b"k"] == b"v"


def test_join_attaches_private_fold_keys_and_drops_unmatched_requests():
    import pyarrow as pa

    table = feature_table(np.asarray(["h1", "h2"]), {"wbm_hr": np.ones((2, 256))}, {"k": "v"})
    keys = pa.Table.from_pylist(
        [{"request_sha256": "h1", "outer_fold": 0, "inner_fold": 2, "cutoff_floating": "x"}]
    )
    joined = join_features(table, keys)
    assert joined.num_rows == 1 and joined.to_pylist()[0]["inner_fold"] == 2
    assert len(joined.to_pylist()[0]["vector"]) == 256 and joined.schema.metadata[b"k"] == b"v"
    with pytest.raises(ValueError, match="repeats"):
        join_features(table, pa.concat_tables([keys, keys]))


def test_moment_without_a_full_patch_is_unsupported_and_its_vector_null(tmp_path):
    hr = [70.0] * 168
    for h in range(7, 168, 8):  # >= 24 observed hours, but every 8-hour patch has a gap
        hr[h] = None
    hashes, values, _ = read_requests(write(tmp_path, [request(hr), request([70.0] * 168)]))
    arrays = model_inputs(values, MEANS, STDS)
    support = moment_patch_support(arrays["moment_mask"])
    assert support[:, 0].tolist() == [False, True]
    table = feature_table(
        np.asarray(hashes),
        {"moment_hr": np.zeros((2, 1024)), "wbm_hr": np.ones((2, 256))},
        {},
        {"moment_hr": support[:, 0]},
    )
    rows = {(r["request_sha256"], r["model"]): r for r in table.to_pylist()}
    gap = rows[(hashes[0], "moment_hr")]
    assert gap["supported"] is False and gap["vector"] is None and gap["finite"] is True
    assert rows[(hashes[1], "moment_hr")]["supported"] is True
    assert all(rows[(h, "wbm_hr")]["supported"] for h in hashes)
    nan = feature_table(np.asarray(["x"]), {"wbm_hr": np.full((1, 256), np.nan)}, {})
    assert nan.to_pylist()[0]["supported"] is False and nan.to_pylist()[0]["vector"] is None
