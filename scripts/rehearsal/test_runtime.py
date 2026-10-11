"""Protect evidence completeness: matching a subset is not equality."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from runtime import RehearsalFailure, agreement, validation_packet


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


if __name__ == "__main__":
    unittest.main()
