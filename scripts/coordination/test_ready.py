"""Checks that missing evidence or malformed dependencies cannot unlock work."""

import unittest

from ready import issue_graph, queue_status


def issue(number, dependency_line="None. Start now.", state="open", reason=None, labels=()):
    return {
        "number": number,
        "body": f"## Dependencies\n\n{dependency_line}\n\nRequired scope.",
        "state": state,
        "state_reason": reason,
        "labels": [{"name": label} for label in labels],
    }


class QueueTests(unittest.TestCase):
    def test_ready_label_cannot_override_open_or_rejected_dependency(self):
        for state, reason in [("open", None), ("closed", "not_planned"), ("closed", None)]:
            with self.subTest(state=state, reason=reason):
                issues, graph = issue_graph([
                    issue(1, state=state, reason=reason),
                    issue(2, "#1", labels=["status:ready"]),
                ])
                self.assertEqual(queue_status(2, issues, graph, set())[0], "WAIT")

    def test_completed_dependency_unlocks_candidate_only(self):
        issues, graph = issue_graph([
            issue(1, state="closed", reason="completed"), issue(2, "#1")])
        self.assertEqual(queue_status(2, issues, graph, set())[0], "DEPENDENCIES MET")

    def test_active_claims_and_external_blockers_are_preserved(self):
        issues, graph = issue_graph([
            issue(1), issue(2, labels=["status:in-progress"]),
            issue(3, labels=["status:blocked"]), issue(4, labels=["status:review"])])
        self.assertEqual(queue_status(1, issues, graph, {1})[0], "ACTIVE")
        self.assertEqual(queue_status(2, issues, graph, set())[0], "ACTIVE")
        self.assertEqual(queue_status(3, issues, graph, set())[0], "CHECK BLOCKER")
        self.assertEqual(queue_status(4, issues, graph, set())[0], "REVIEW")

    def test_missing_malformed_and_cyclic_dependencies_fail_closed(self):
        for records in [
            [issue(1, "#99")], [issue(1, "probably none")],
            [issue(1, "#2"), issue(2, "#1")], [{**issue(1), "body": ""}],
        ]:
            with self.subTest(records=records), self.assertRaises(ValueError):
                issue_graph(records)

    def test_tracker_and_pull_requests_are_not_work_items(self):
        issues, graph = issue_graph([
            issue(1), {**issue(26), "body": "", "labels": [{"name": "tracking"}]},
            {**issue(27), "body": "", "pull_request": {}},
        ])
        self.assertEqual(set(issues), {1})
        self.assertEqual(graph, {1: []})


if __name__ == "__main__":
    unittest.main()
