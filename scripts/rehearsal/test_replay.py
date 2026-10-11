"""Protect replay integrity, original provenance and the offline error boundary."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from http.server import HTTPServer
from pathlib import Path

from replay import REPO, OfflineReplayProvider, ReplayFailure, handler, page, receipt, save, sha256
from synthetic_replay import gapped_target_job

from hachi.contracts.api import ReportJob


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.json"
        self.cache = self.root / "cache.json"
        self.job = json.loads((REPO / "contracts/fixtures/ReportJob/completed.json").read_bytes())
        self.write_source(self.job)

    def write_source(self, value):
        self.source.write_text(json.dumps(value))
        os.chmod(self.source, 0o600)

    def provider(self):
        summary = save(self.source, self.cache)
        return OfflineReplayProvider(self.cache, summary["cache_sha256"])

    def test_entire_response_preserved_and_file_private(self):
        provider = self.provider()
        before = provider.cache().source.model_dump(mode="json")
        replay = provider.report().model_dump(mode="json")
        info = replay["result"].pop("replay")
        replay["result"]["replay"] = None
        self.assertEqual(replay, before)
        self.assertEqual(info["source_report_id"], before["report_id"])
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)
        self.assertEqual(receipt(provider)["forecast_points_compared"], 48)
        self.assertIsNone(provider.cache().source.result.root.replay)
        with self.assertRaisesRegex(ReplayFailure, "CACHE_EXISTS"):
            save(self.source, self.cache)

    def test_pending_and_already_replayed_sources_refused(self):
        self.job["state"], self.job["result"] = "running", None
        self.write_source(self.job)
        with self.assertRaisesRegex(ReplayFailure, "SOURCE_INVALID"):
            save(self.source, self.cache)
        self.job = json.loads((REPO / "contracts/fixtures/ReportJob/completed.json").read_bytes())
        self.job["result"]["replay"] = {
            "source_report_id": self.job["report_id"],
            "recorded_at_utc": datetime.now(UTC).isoformat(),
        }
        self.write_source(self.job)
        with self.assertRaisesRegex(ReplayFailure, "SOURCE_INVALID"):
            save(self.source, self.cache)

    def test_outer_pin_refuses_rehashed_payload_substitution(self):
        provider = self.provider()
        data = json.loads(self.cache.read_bytes())
        data["source"]["result"]["forecast"]["series"][0]["points"][0]["median"] += 1
        changed_job = ReportJob.model_validate_json(json.dumps(data["source"]))
        from replay import canonical

        data["source_response_sha256"] = sha256(canonical(changed_job))
        self.cache.write_text(json.dumps(data))
        with self.assertRaisesRegex(ReplayFailure, "CACHE_INTEGRITY_FAILED"):
            provider.report()

    def test_schema_change_corruption_and_missing_cache_fail_closed(self):
        self.provider()
        data = json.loads(self.cache.read_bytes())
        data["contract_schema_sha256"] = "0" * 64
        self.cache.write_text(json.dumps(data))
        provider = OfflineReplayProvider(self.cache, sha256(self.cache.read_bytes()))
        with self.assertRaisesRegex(ReplayFailure, "CONTRACT_SCHEMA_CHANGED"):
            provider.report()
        self.cache.write_text("{invalid")
        provider = OfflineReplayProvider(self.cache, sha256(self.cache.read_bytes()))
        with self.assertRaisesRegex(ReplayFailure, "CACHE_INVALID"):
            provider.report()
        self.cache.unlink()
        with self.assertRaisesRegex(ReplayFailure, "CACHE_MISSING"):
            provider.report()

    def test_private_files_and_no_symlink_reads(self):
        self.provider()
        os.chmod(self.cache, 0o644)
        provider = OfflineReplayProvider(self.cache, sha256(self.cache.read_bytes()))
        with self.assertRaisesRegex(ReplayFailure, "PRIVATE_FILE_REQUIRED"):
            provider.report()
        link = self.root / "link"
        link.symlink_to(self.source)
        with self.assertRaisesRegex(ReplayFailure, "CACHE_UNREADABLE"):
            save(link, self.root / "other.json")

    def test_point_only_unavailable_and_error_views_keep_meaning(self):
        fixtures = REPO / "contracts/fixtures/ReportResult"
        for name in (
            "ok-physiology-forecast-point-only",
            "unavailable-illness-onset",
            "error-artifact-integrity",
        ):
            with self.subTest(name=name):
                result = json.loads((fixtures / (name + ".json")).read_bytes())
                job = {
                    **self.job,
                    "report_id": result["report_id"],
                    "request": {
                        "schema_version": "0.1",
                        "subject_id": result["subject_id"],
                        "as_of": result["as_of"],
                        "task": result["task"],
                    },
                    "result": result,
                }
                if result["task"] == "physiology_forecast":
                    job["request"].update(
                        resolution="hour", horizon_hours=24, metrics=["heart_rate"]
                    )
                elif result["task"] == "illness_onset":
                    job["request"].update(horizon_hours=24)
                self.write_source(job)
                destination = self.root / (name + ".json")
                summary = save(self.source, destination)
                provider = OfflineReplayProvider(destination, summary["cache_sha256"])
                body = page(provider.report()).decode()
                self.assertNotIn(result["subject_id"], body)
                self.assertNotIn(result["report_id"], body)
                self.assertIn("original data mode", body)
                self.assertNotIn('data-interval-band="true"', body)
                if result["status"] == "ok":
                    self.assertIn("no interval or coverage claim", body)
                else:
                    self.assertIn(result.get("reason_code", result.get("error_code")), body)
                self.assertTrue(receipt(provider)["entire_response_equal_except_replay"])

    def test_actual_transport_no_store_and_visible_missing_error(self):
        provider = self.provider()
        with HTTPServer(("127.0.0.1", 0), handler(provider)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with opener.open(base + "/replay/report") as response:
                    job = ReportJob.model_validate_json(response.read())
                    self.assertIsNotNone(job.result.root.replay)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.cache.unlink()
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    opener.open(base)
                response = caught.exception
                self.assertEqual(response.code, 409)
                body = response.read().decode()
                response.close()
                self.assertIn('role="alert"', body)
                self.assertIn("CACHE_MISSING", body)
                self.assertNotIn(str(self.root), body)
                self.assertIn("No live request or synthetic fallback", body)
            finally:
                server.shutdown()
                thread.join()

    def test_exact_cutoff_and_gapped_target_windows_are_visible(self):
        self.write_source(gapped_target_job().model_dump(mode="json"))
        job = self.provider().report()
        result = job.result.root
        body = page(job).decode()
        self.assertIn(result.as_of.isoformat(), body)
        for series in result.forecast.series:
            for point in series.points:
                self.assertIn(point.interval_start_utc.isoformat(), body)
                self.assertIn(point.interval_end_utc.isoformat(), body)
        self.assertIn("METRIC_NOT_OBSERVED", body)
        self.assertNotIn('data-interval-band="true"', body)

        class Positions(HTMLParser):
            def __init__(self):
                super().__init__()
                self.x = []

            def handle_starttag(self, tag, attrs):
                if tag == "circle":
                    self.x.append(float(dict(attrs)["cx"]))

        parsed = Positions()
        parsed.feed(body)
        # The requested 24-hour domain is shared by both series, preserving
        # initial, between-window and trailing missing target periods.
        self.assertEqual(parsed.x, [63.75, 86.25, 108.75, 266.25, 288.75])

    def test_actual_host_refusal_and_post_cannot_read_or_mutate_cache(self):
        provider = self.provider()
        original = self.cache.read_bytes()
        with HTTPServer(("127.0.0.1", 0), handler(provider)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                request = urllib.request.Request(base + "/replay/report")
                request.add_header("Host", f"localhost:{server.server_port}")
                with self.assertRaises(urllib.error.HTTPError) as refused:
                    opener.open(request)
                with refused.exception as response:
                    self.assertEqual(response.code, 409)
                    self.assertEqual(json.loads(response.read())["error_code"], "HOST_REFUSED")
                with self.assertRaises(urllib.error.HTTPError) as post:
                    opener.open(urllib.request.Request(base + "/replay/report", data=b"{}"))
                with post.exception as response:
                    self.assertEqual(response.code, 501)
                self.assertEqual(self.cache.read_bytes(), original)
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
