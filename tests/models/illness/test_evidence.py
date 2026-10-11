"""Evidence assembly must retain causal scope and disclose transformations."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pytest

from hachi.models.illness.evidence import input_hashes, label_grid_check, packet_scores


def test_packet_inventory_and_score_roundtrip(tmp_path):
    from datetime import UTC, datetime

    from hachi.evaluation.serialization import document_bytes
    from hachi.models.illness.data import Window
    from hachi.models.illness.metrics import Score

    expected = []
    for i in range(3):
        row = Score(
            Window(
                f"synthetic-{i}",
                datetime(2020, 1, 1, tzinfo=UTC),
                24,
                False,
                None,
                None,
                None,
                (0.0, None),
            ),
            0.2,
            0.3,
        )
        packet = tmp_path / f"inner-{i}-24h-tree"
        packet.mkdir()
        (packet / "predictions.json").write_bytes(document_bytes([row]))
        expected.append(row)
    assert packet_scores(tmp_path, 24, "tree") == expected
    before = input_hashes(tmp_path)
    assert len(before) == 3
    path = tmp_path / "inner-0-24h-tree/predictions.json"
    assert before[str(path.relative_to(tmp_path))] == hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_bytes(b"[]\n")
    assert input_hashes(tmp_path) != before


def test_label_recheck_uses_only_development_and_rejects_mismatch(monkeypatch):
    import hachi.models.illness.evidence as evidence

    fold = SimpleNamespace(
        outer_fold=0, validation_subjects=("synthetic-dev",), test_subjects=("synthetic-sealed",)
    )
    monkeypatch.setattr(evidence, "clinical_fold_plan", lambda *args: SimpleNamespace(folds=[fold]))
    rows = [
        {
            "subject_id": "synthetic-dev",
            "cutoff_utc": "synthetic-coordinate",
            **{f"onset_{h}h": "negative" for h in (24, 48, 72)},
            **{f"onset_episode_{h}h": None for h in (24, 48, 72)},
        }
    ]

    def guarded(snapshot, name=None, subjects=None, **kwargs):
        assert tuple(subjects) == fold.validation_subjects
        return pa.Table.from_pylist(rows)

    monkeypatch.setattr(evidence, "read_table", guarded)
    monkeypatch.setattr(evidence, "onset_labels", guarded)
    protocol = SimpleNamespace(active_outer_fold=0)
    result = label_grid_check(Path("synthetic"), protocol)
    assert result == {
        "development_cutoffs": 1,
        "onset_label_episode_comparisons": 6,
        "mismatches": 0,
        "outer_test_read": False,
    }
    wrong = [{**rows[0], "onset_24h": "positive"}]
    monkeypatch.setattr(
        evidence, "onset_labels", lambda *args, **kwargs: pa.Table.from_pylist(wrong)
    )
    with pytest.raises(ValueError, match="grid differs"):
        label_grid_check(Path("synthetic"), protocol)
