"""Protect evidence completeness: matching a subset is not equality."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from runtime import (
    REPO,
    RehearsalFailure,
    agreement,
    require_abstention,
    require_point_only,
    require_validation_origins,
    validation_packet,
)

from hachi.contracts.manifests import SplitManifest
from hachi.contracts.results import PhysiologyForecastResult


class AgreementTests(unittest.TestCase):
    def test_equal_points(self):
        summary = agreement({1: 70.0, 2: 71.0}, {1: 70.0, 2: 71.0})
        self.assertEqual(summary["points_compared"], 2)
        self.assertEqual(summary["points_mismatched"], 0)
        self.assertEqual(summary["missing_api_points"], 0)
        self.assertEqual(summary["extra_api_points"], 0)

    def test_truncated_api_is_not_equal(self):
        summary = agreement({1: 70.0}, {1: 70.0, 2: 71.0})
        self.assertEqual(summary["missing_api_points"], 1)

    def test_extra_points_are_not_equal(self):
        summary = agreement({1: 70.0, 2: 71.0}, {1: 70.0})
        self.assertEqual(summary["extra_api_points"], 1)

    def test_changed_value_is_not_equal(self):
        summary = agreement({1: 72.0}, {1: 70.0})
        self.assertEqual(summary["points_mismatched"], 1)
        self.assertEqual(summary["max_abs_difference"], 2.0)

    def test_rehashing_private_packet_does_not_replace_published_freeze(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet = root / "outer-0-inner-0/evaluations/example"
            packet.mkdir(parents=True)
            changed = b'"changed private split"'
            (packet / "split.json").write_bytes(changed)
            (packet / "sha256.json").write_text(
                json.dumps({"split.json": hashlib.sha256(changed).hexdigest()})
            )
            index = root / "published.json"
            index.write_text(
                json.dumps(
                    {"packets": {"outer-0-inner-0/evaluations/example": {"split.json": "0" * 64}}}
                )
            )
            with self.assertRaisesRegex(RehearsalFailure, "published frozen evidence"):
                validation_packet(packet, index)


class EvidenceGuardTests(unittest.TestCase):
    def test_test_origin_and_opened_test_are_refused(self):
        raw = json.loads((REPO / "contracts/fixtures/SplitManifest/fold-0.json").read_bytes())
        split = SplitManifest.model_validate_json(json.dumps(raw))
        require_validation_origins(
            split, [{"origin": {"subject_id": split.validation_subjects[0]}}]
        )
        with self.assertRaisesRegex(RehearsalFailure, "inner-validation"):
            require_validation_origins(split, [{"origin": {"subject_id": split.test_subjects[0]}}])
        raw["test_opened_at_utc"] = "2026-10-11T00:00:00Z"
        opened = SplitManifest.model_validate_json(json.dumps(raw))
        with self.assertRaisesRegex(RehearsalFailure, "sealed"):
            require_validation_origins(
                opened, [{"origin": {"subject_id": split.validation_subjects[0]}}]
            )

    def point_only(self):
        return json.loads(
            (
                REPO / "contracts/fixtures/ReportResult/ok-physiology-forecast-point-only.json"
            ).read_bytes()
        )

    def test_source_coverage_must_match_exactly(self):
        result = PhysiologyForecastResult.model_validate_json(json.dumps(self.point_only()))
        coverage = result.provenance.feature_coverage[0].coverage
        require_point_only(result, "heart_rate", coverage)
        with self.assertRaisesRegex(RehearsalFailure, "source history"):
            require_point_only(result, "heart_rate", coverage / 2)

    def test_valid_contract_with_intervals_cannot_pass_point_only_rehearsal(self):
        data = self.point_only()
        series = data["forecast"]["series"][0]
        series.update(interval_calibration="uncalibrated", nominal_coverage=0.8)
        for point in series["points"]:
            point.update(lower=point["median"] - 1, upper=point["median"] + 1)
        result = PhysiologyForecastResult.model_validate_json(json.dumps(data))
        with self.assertRaisesRegex(RehearsalFailure, "claims intervals"):
            require_point_only(result, "heart_rate", result.provenance.feature_coverage[0].coverage)

    def test_point_only_cannot_carry_interval_warning(self):
        data = self.point_only()
        data["warnings"] = [{"code": "UNCALIBRATED_INTERVALS", "message": "Synthetic warning"}]
        result = PhysiologyForecastResult.model_validate_json(json.dumps(data))
        with self.assertRaisesRegex(RehearsalFailure, "interval warning"):
            require_point_only(result, "heart_rate", result.provenance.feature_coverage[0].coverage)

    def test_abstention_only_when_both_references_have_no_points(self):
        require_abstention("unavailable", {}, {})
        for status, packet, direct in (
            ("error", {}, {}),
            ("unavailable", {1: 70.0}, {}),
            ("unavailable", {}, {1: 70.0}),
        ):
            with (
                self.subTest(status=status, packet=bool(packet), direct=bool(direct)),
                self.assertRaisesRegex(RehearsalFailure, "abstention"),
            ):
                require_abstention(status, packet, direct)


if __name__ == "__main__":
    unittest.main()
