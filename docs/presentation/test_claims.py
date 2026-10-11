"""Fail-closed checks for public narrative provenance; no private/model runtime."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("claim_checker", HERE / "check_claims.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ClaimChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((HERE / "claims.json").read_text())

    def changed(self):
        return copy.deepcopy(self.manifest)

    def test_actual_public_sources_render_exact_committed_documents(self):
        for name, value in checker.render(self.manifest).items():
            self.assertEqual(value, (HERE / name).read_text())

    def test_apple_anchor_with_internal_backticks_uses_double_delimiter(self):
        claim = next(c for c in self.manifest["claims"] if c["id"] == "apple-transport")
        anchor = claim["values"]["quote"]["expected"]
        self.assertIn("`INSUFFICIENT_HISTORY`", anchor)
        for name, output in checker.render(self.manifest).items():
            with self.subTest(document=name):
                self.assertTrue(
                    f"source measurement row ``{anchor}``." in output,
                    "anchor must have a double-backtick outer delimiter",
                )
                self.assertFalse(f"source measurement row `{anchor}`." in output)

    def test_simulation_fence_closes_before_separate_evidence_paragraph(self):
        claim = next(c for c in self.manifest["claims"] if c["id"] == "simulation-parameters")
        config = claim["values"]["config"]["expected"]
        outputs = checker.render(self.manifest)
        for name, output in outputs.items():
            with self.subTest(document=name):
                self.assertTrue(
                    f"```toml\n{config}\n```\n\n" in output,
                    "configuration fence must close on a standalone line",
                )
        self.assertTrue(
            "\n```\n\n [Evidence](CLAIMS.md#simulation-parameters).\n" in outputs["NARRATIVE.md"],
            "evidence link must follow the closing fence in a separate paragraph",
        )
        self.assertNotIn("``` [Evidence]", outputs["NARRATIVE.md"])

    def test_altered_number_cannot_be_rounded_into_a_claim(self):
        manifest = self.changed()
        manifest["claims"][0]["values"]["people"]["expected"] += 1
        with self.assertRaises(ValueError):
            checker.render(manifest)

    def test_literal_number_cannot_be_added_beside_bound_values(self):
        manifest = self.changed()
        manifest["claims"][0]["text"] += " Accuracy 99%."
        with self.assertRaises(ValueError):
            checker.render(manifest)

    def test_boolean_does_not_pass_as_integer(self):
        manifest = self.changed()
        manifest["claims"][0]["values"]["people"]["expected"] = True
        with self.assertRaises(ValueError):
            checker.render(manifest)

    def test_altered_source_digest_fails(self):
        manifest = self.changed()
        manifest["sources"]["chronos"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            checker.render(manifest)

    def test_changed_worktree_source_is_refused_even_with_matching_pin(self):
        original = Path.read_bytes
        target = checker.ROOT / self.manifest["sources"]["chronos"]["path"]

        def altered(path):
            result = original(path)
            return result + b"\n" if path == target else result

        with patch.object(Path, "read_bytes", altered), self.assertRaises(ValueError):
            checker.render(self.manifest)

    def test_bad_selector_does_not_fall_back_to_expected_value(self):
        manifest = self.changed()
        manifest["claims"][0]["values"]["people"]["pointer"] = "/missing"
        with self.assertRaises(KeyError):
            checker.render(manifest)

    def test_text_anchor_change_fails(self):
        manifest = self.changed()
        claim = next(c for c in manifest["claims"] if c["id"] == "confidence-method")
        claim["values"]["quote"]["expected"] = "Unsupported accuracy claim."
        with self.assertRaises(ValueError):
            checker.render(manifest)

    def test_superseded_recovery_path_is_refused(self):
        manifest = self.changed()
        manifest["sources"]["chronos"]["path"] = "reports/models/recovery/phase1.json"
        with self.assertRaises(ValueError):
            checker.render(manifest)

    def test_private_and_parent_paths_are_refused(self):
        for path in ["/approved/private/report.json", "reports/../../private/report.json"]:
            with self.subTest(path=path):
                manifest = self.changed()
                manifest["sources"]["chronos"]["path"] = path
                with self.assertRaises(ValueError):
                    checker.render(manifest)

    def test_scenario_admission_is_limited_to_public_readme(self):
        manifest = self.changed()
        manifest["sources"]["scenario-report"]["path"] = "src/hachi/scenarios/model.py"
        with self.assertRaisesRegex(ValueError, "outside public evidence scope"):
            checker.render(manifest)

    def test_new_selection_and_parameter_bindings_fail_on_tampering(self):
        for identifier, field, changed in [
            ("selected-errors", "mae", 0.0),
            ("simulation-parameters", "config", "sample_minutes = 1"),
        ]:
            with self.subTest(claim=identifier):
                manifest = self.changed()
                claim = next(c for c in manifest["claims"] if c["id"] == identifier)
                claim["values"][field]["expected"] = changed
                with self.assertRaises(ValueError):
                    checker.render(manifest)

    def test_preparation_cannot_grant_completion_or_test_authority(self):
        for key, value in [("completion", "complete"), ("final_test_authorized", True)]:
            manifest = self.changed()
            manifest[key] = value
            with self.assertRaises(ValueError):
                checker.render(manifest)

    def test_unbound_template_number_is_refused(self):
        for statement in [
            "Accuracy 99%.",
            "Accuracy `99%`.",
            "[99% accuracy](https://example.org)",
        ]:
            with self.subTest(statement=statement), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory)
                destination.joinpath("NARRATIVE.template.md").write_text(
                    (HERE / "NARRATIVE.template.md").read_text() + "\n" + statement + "\n"
                )
                with patch.object(checker, "HERE", destination), self.assertRaises(ValueError):
                    checker.render(self.manifest)

    def test_unknown_or_deleted_template_claim_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            destination.joinpath("NARRATIVE.template.md").write_text("{{unknown}}\n")
            with patch.object(checker, "HERE", destination), self.assertRaises(ValueError):
                checker.render(self.manifest)


if __name__ == "__main__":
    unittest.main()
