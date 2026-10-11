"""Private saved-response replay: no inference, live fallback, or participant logging."""

import argparse
import hashlib
import html
import json
import logging
import os
import stat
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import ValidationError, model_validator

from hachi.api.settings import git_dirty, git_sha
from hachi.contracts.api import ReportJob
from hachi.contracts.base import Contract, Sha256, UtcDatetime
from hachi.contracts.results import PhysiologyForecastResult
from hachi.storage import private_directory

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "contracts/schema/hachi.schema.json"
MAX_BYTES = 16 * 1024 * 1024


class ReplayFailure(Exception):
    """Codes alone cross the HTTP/CLI boundary; validation details stay private."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(job: ReportJob) -> bytes:
    return json.dumps(job.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


class ReplayCache(Contract):
    """Local format composed from authoritative contracts, not an API schema change.

    The whole cache digest must be pinned separately by its consumer. The embedded
    response digest detects accidental corruption, not an adversary who can rehash.
    """

    format_version: Literal["hachi-offline-replay-1"]
    recorded_at_utc: UtcDatetime
    contract_schema_sha256: Sha256
    source_response_sha256: Sha256
    source: ReportJob

    @model_validator(mode="after")
    def _check(self) -> Self:
        result = self.source.result
        if self.source.state != "completed" or result is None:
            raise ValueError("only completed responses can be saved")
        if result.root.replay is not None:
            raise ValueError("a replay cannot be relabelled as an original live response")
        if self.recorded_at_utc < self.source.updated_at_utc:
            raise ValueError("recording cannot predate the completed response")
        if self.source_response_sha256 != sha256(canonical(self.source)):
            raise ValueError("source response checksum differs")
        return self


def private_read(path: Path) -> bytes:
    """Read a bounded, private regular file without following its final symlink."""
    if path.resolve().is_relative_to(REPO):
        raise ReplayFailure("PRIVATE_PATH_REQUIRED")
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ReplayFailure("PRIVATE_FILE_REQUIRED")
            if info.st_size > MAX_BYTES:
                raise ReplayFailure("CACHE_TOO_LARGE")
            data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ReplayFailure("CACHE_TOO_LARGE")
            return data
    except FileNotFoundError:
        raise ReplayFailure("CACHE_MISSING") from None
    except OSError:
        raise ReplayFailure("CACHE_UNREADABLE") from None


def save(source_path: Path, destination: Path) -> dict:
    try:
        job = ReportJob.model_validate_json(private_read(source_path))
        cache = ReplayCache(
            format_version="hachi-offline-replay-1",
            recorded_at_utc=datetime.now(UTC),
            contract_schema_sha256=sha256(SCHEMA.read_bytes()),
            source_response_sha256=sha256(canonical(job)),
            source=job,
        )
    except ValidationError:
        raise ReplayFailure("SOURCE_INVALID") from None
    if destination.resolve().is_relative_to(REPO):
        raise ReplayFailure("PRIVATE_PATH_REQUIRED")
    private_directory(destination.parent)
    data = cache.model_dump_json(indent=2).encode() + b"\n"
    try:
        with os.fdopen(
            os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
        ) as out:
            out.write(data)
    except FileExistsError:
        raise ReplayFailure("CACHE_EXISTS") from None
    return {
        "saved": True,
        "cache_sha256": sha256(data),
        "source_response_sha256": cache.source_response_sha256,
        "contract_schema_sha256": cache.contract_schema_sha256,
        "original_data_mode": job.result.root.data_mode,
    }


class ReportProvider(Protocol):
    """Shared caller seam: live clients may implement it; replay never calls them."""

    def report(self) -> ReportJob: ...


class OfflineReplayProvider:
    def __init__(self, path: Path, expected_cache_sha256: str):
        self.path = path
        self.expected_cache_sha256 = expected_cache_sha256

    def cache(self) -> ReplayCache:
        data = private_read(self.path)
        if sha256(data) != self.expected_cache_sha256:
            raise ReplayFailure("CACHE_INTEGRITY_FAILED")
        try:
            cache = ReplayCache.model_validate_json(data)
        except ValidationError:
            raise ReplayFailure("CACHE_INVALID") from None
        if cache.contract_schema_sha256 != sha256(SCHEMA.read_bytes()):
            raise ReplayFailure("CONTRACT_SCHEMA_CHANGED")
        return cache

    def report(self) -> ReportJob:
        cache = self.cache()
        value = cache.source.model_dump(mode="json")
        value["result"]["replay"] = {
            "source_report_id": cache.source.report_id,
            "recorded_at_utc": cache.recorded_at_utc.isoformat(),
        }
        # Revalidate rather than model_copy: that operation bypasses invariants.
        return ReportJob.model_validate_json(json.dumps(value))


def receipt(provider: OfflineReplayProvider) -> dict:
    cache, replay = provider.cache(), provider.report()
    original = cache.source.model_dump(mode="json")
    projected = replay.model_dump(mode="json")
    projected["result"]["replay"] = None
    if projected != original:
        raise ReplayFailure("REPLAY_RESPONSE_CHANGED")
    result = replay.result.root
    provenance = None if result.status == "error" else result.provenance
    points = (
        sum(len(series.points) for series in result.forecast.series)
        if isinstance(result, PhysiologyForecastResult)
        else 0
    )
    return {
        "format_version": "hachi-replay-evidence-1",
        "consumer_git_sha": git_sha(REPO),
        "script_sha256": sha256(Path(__file__).read_bytes()),
        "uv_lock_sha256": sha256((REPO / "uv.lock").read_bytes()),
        "cache_sha256": provider.expected_cache_sha256,
        "source_response_sha256": cache.source_response_sha256,
        "contract_schema_sha256": cache.contract_schema_sha256,
        "original_data_mode": result.data_mode,
        "replay_metadata_present": result.replay is not None,
        "entire_response_equal_except_replay": True,
        "forecast_points_compared": points,
        "source_git_sha": result.git_sha,
        "artifact": provenance.artifact.model_dump(mode="json")
        if provenance is not None and provenance.artifact is not None
        else None,
        "dataset_snapshot": provenance.dataset_snapshot.model_dump(mode="json")
        if provenance is not None and provenance.dataset_snapshot is not None
        else None,
        "live_api_used": False,
    }


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def page(job: ReportJob) -> bytes:
    """Dedicated rehearsal viewer; does not claim Coffee's app integration.

    No subject/report identifiers appear in the HTML. Real numeric content still
    stays private; only synthetic pages may be screenshotted or snapshotted.
    """
    result = job.result.root
    replay = result.replay
    if replay is None:
        raise ReplayFailure("REPLAY_METADATA_MISSING")
    provenance = None if result.status == "error" else result.provenance
    artifact = provenance.artifact if provenance else None
    snapshot = provenance.dataset_snapshot if provenance else None
    details = (
        f"<p>Replay · original data mode: <strong>{escape(result.data_mode)}</strong></p>"
        f"<p>Recorded: {escape(replay.recorded_at_utc.isoformat())}</p>"
        f"<p>Source generated: {escape(result.generated_at_utc.isoformat())}</p>"
        f"<p>Source code: {escape(result.git_sha)}</p>"
        f"<p>Model artifact: {escape(artifact.artifact_id if artifact else 'Unavailable')}</p>"
        f"<p>Artifact SHA256: {escape(artifact.artifact_sha256 if artifact else 'Unavailable')}</p>"
        f"<p>Dataset SHA256: {escape(snapshot.snapshot_sha256 if snapshot else 'Unavailable')}</p>"
    )
    content = ""
    if isinstance(result, PhysiologyForecastResult):
        for series in result.forecast.series:
            points = series.points
            values = [p.median for p in points]
            lo = min(p.lower if p.lower is not None else p.median for p in points)
            hi = max(p.upper if p.upper is not None else p.median for p in points)
            span = hi - lo or 1
            count = len(points)

            def xy(index: int, value: float, n=count, low=lo, width=span) -> str:
                x = 30 + index * 540 / max(1, n - 1)
                y = 170 - (value - low) * 140 / width
                return f"{x:.4f},{y:.4f}"

            line = " ".join(xy(i, value) for i, value in enumerate(values))
            band = ""
            if series.interval_calibration != "none":
                boundary = [xy(i, p.lower) for i, p in enumerate(points)]
                boundary += [xy(i, p.upper) for i, p in reversed(list(enumerate(points)))]
                band = (
                    f'<polygon data-interval-band="true" points="{" ".join(boundary)}" '
                    'fill="#dbeafe"/>'
                )
            circles = "".join(
                f'<circle data-median="{p.median}" cx="{xy(i, p.median).split(",")[0]}" '
                f'cy="{xy(i, p.median).split(",")[1]}" r="3" fill="#1d4ed8"/>'
                for i, p in enumerate(points)
            )
            rows = "".join(
                f'<tr><td>{i + 1}</td><td data-value="median">{p.median}</td>'
                f"<td>{p.lower if p.lower is not None else '—'}</td>"
                f"<td>{p.upper if p.upper is not None else '—'}</td></tr>"
                for i, p in enumerate(points)
            )
            interval = (
                "Point-only forecast · no interval or coverage claim"
                if series.interval_calibration == "none"
                else (
                    f"{series.interval_calibration} intervals · "
                    f"nominal coverage {series.nominal_coverage}"
                )
            )
            content += (
                f"<section><h2>{escape(series.metric)} · {escape(series.unit)}</h2>"
                f"<p>{escape(interval)}</p>"
                '<svg viewBox="0 0 600 200" role="img" '
                'aria-label="Saved forecast; exact values in table">'
                f'{band}<polyline points="{line}" fill="none" stroke="#1d4ed8"/>{circles}</svg>'
                "<table><caption>Exact saved forecast values by future bin</caption><thead><tr>"
                "<th>Bin</th><th>Median</th><th>Lower</th><th>Upper</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></section>"
            )
    elif result.status == "unavailable":
        requirements = "".join(f"<li>{escape(r)}</li>" for r in result.requirements)
        content = f"<h2>Unavailable</h2><p>{escape(result.reason_code)}</p><ul>{requirements}</ul>"
    elif result.status == "error":
        content = (
            f"<h2>Report error</h2><p>{escape(result.error_code)}</p>"
            f"<p>{escape(result.message)}</p>"
        )
    else:
        content = (
            f"<h2>Saved {escape(result.task)} result</h2>"
            "<p>This rehearsal viewer renders forecasts only.</p>"
        )
    quality = " ".join(
        f"<li>{escape(c.metric)}: {escape(c.coverage)}</li>"
        for c in (provenance.feature_coverage if provenance else [])
    )
    warnings = " ".join(f"<li>{escape(w.code)}</li>" for w in result.warnings)
    return document(
        details + content + f"<h2>Source quality</h2><ul>{quality}</ul><ul>{warnings}</ul>"
    )


def document(content: str) -> bytes:
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Hachi offline replay rehearsal</title><style>"
        "body{font:16px system-ui;max-width:840px;margin:24px auto;padding:0 16px;color:#172033}"
        "p{overflow-wrap:anywhere}svg{width:100%;max-height:260px}table{width:100%;border-collapse:collapse}"
        "th,td{text-align:left;padding:8px;border-bottom:1px solid #ddd}"
        "header{border-bottom:3px solid #2563eb}"
        "</style><header><h1>Offline replay rehearsal</h1>"
        "<p>Saved response only · no live inference. "
        "This viewer is separate from the app integration.</p></header><main>"
        + content
        + "</main></html>"
    ).encode()


def handler(provider: OfflineReplayProvider):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # request paths and third-party messages must not enter logs

        def do_GET(self):
            try:
                if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                    raise ReplayFailure("HOST_REFUSED")
                if self.path not in ("/", "/replay/report"):
                    self.send_error(404, "Not found")
                    return
                job = provider.report()
                body = page(job) if self.path == "/" else job.model_dump_json().encode()
                self.respond(200, body, "text/html" if self.path == "/" else "application/json")
            except ReplayFailure as error:
                self.failure(str(error))
            except Exception:
                # Even unexpected reader/renderer failures must not echo private values.
                self.failure("REPLAY_READ_FAILED")

        def failure(self, code: str):
            body = (
                document(
                    f'<section role="alert"><h2>Replay unavailable</h2><p>{escape(code)}</p>'
                    "<p>Restore the pinned private cache and matching contracts, then reload. "
                    "No live request or synthetic fallback was made.</p></section>"
                )
                if self.path == "/"
                else json.dumps({"error_code": code, "live_fallback": False}).encode()
            )
            self.respond(409, body, "text/html" if self.path == "/" else "application/json")

        def respond(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; connect-src 'self'; "
                "style-src 'unsafe-inline'; frame-ancestors 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

    return Handler


class ReplayServer(HTTPServer):
    def handle_error(self, request, client_address):
        # BaseServer prints tracebacks for disconnected clients; those can contain data.
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("save")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--cache", type=Path, required=True)
    for name in ("check", "serve"):
        command = sub.add_parser(name)
        command.add_argument("--cache", type=Path, required=True)
        command.add_argument("--expected-cache-sha256", required=True)
        if name == "serve":
            command.add_argument("--port", type=int, default=5180)
    args = parser.parse_args()
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    try:
        if git_dirty(REPO):
            raise ReplayFailure("CLEAN_COMMITTED_CHECKOUT_REQUIRED")
        if args.command == "save":
            result = save(args.source, args.cache)
        else:
            provider = OfflineReplayProvider(args.cache, args.expected_cache_sha256)
            if args.command == "serve":
                with ReplayServer(("127.0.0.1", args.port), handler(provider)) as server:
                    server.serve_forever()
                return 0
            result = receipt(provider)
        print(json.dumps(result, indent=2))
        return 0
    except KeyboardInterrupt:
        return 0
    except ReplayFailure as error:
        print(json.dumps({"ok": False, "error_code": str(error)}))
    except Exception as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
