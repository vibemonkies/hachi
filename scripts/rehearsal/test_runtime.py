"""Protect evidence completeness: matching a subset is not equality."""

import unittest

from runtime import agreement


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


if __name__ == "__main__":
    unittest.main()
