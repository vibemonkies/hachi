"""The FastAPI app for docs/CONTRACTS.md's API surface.

Bodies are validated with the contracts' own strict JSON rules (`model_validate_json`) and
responses are serialized from validated contract models. Every non-2xx response is an
ApiError. JSON endpoints require `application/json`, so a cross-site page cannot send them
without a CORS preflight; the Host header must name this loopback service.
"""

import json
import logging
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException

from hachi.contracts.api import (
    ApiError,
    Coverage,
    HealthStatus,
    ImportStatus,
    ReportJob,
    SelfReportHistory,
)
from hachi.contracts.requests import ReportRequest, ScenarioRequest, SelfReportRequest
from hachi.contracts.results import ReportResult
from hachi.storage import Metadata, is_name, private_directory

from .catalog import Catalog
from .errors import ApiProblem, parse_body, path_id, validation_problem
from .service import CoverageParams, HistoryParams, Service, UploadParams
from .settings import Settings

log = logging.getLogger("hachi.api")

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
UPLOAD_TYPES = frozenset(
    {
        "application/zip",
        "application/x-zip-compressed",
        "application/xml",
        "text/xml",
        "application/octet-stream",
    }
)
MAX_JSON_BYTES = 1024 * 1024


def _json(model: BaseModel, status: int = 200) -> Response:
    return Response(model.model_dump_json(), status_code=status, media_type="application/json")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "req-" + secrets.token_hex(8)


def _error(request: Request, problem: ApiProblem) -> Response:
    response = _json(problem.document(_request_id(request)), problem.status)
    response.headers["X-Request-Id"] = _request_id(request)
    return response


class _Guard:
    """Pure ASGI: assigns the request id and refuses Host headers other than this service."""

    def __init__(self, app, allowed_hosts: frozenset[str]) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        incoming = headers.get("x-request-id", "")
        request_id = incoming if is_name(incoming) else "req-" + secrets.token_hex(8)
        scope.setdefault("state", {})["request_id"] = request_id
        host = headers.get("host", "")
        hostname = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        if hostname not in self.allowed_hosts:
            problem = ApiProblem("VALIDATION_FAILED", "Unexpected Host header.", status=400)
            body = problem.document(request_id).model_dump_json().encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"x-request-id", request_id.encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                names = {k.lower() for k, _ in message.get("headers", [])}
                if b"x-request-id" not in names:
                    message["headers"] = [
                        *message.get("headers", []),
                        (b"x-request-id", request_id.encode()),
                    ]
            await send(message)

        await self.app(scope, receive, send_with_id)


async def _json_body(request: Request) -> bytes:
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media != "application/json":
        raise ApiProblem("VALIDATION_FAILED", "Send the body as application/json.", status=415)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_JSON_BYTES:
            raise ApiProblem("PAYLOAD_TOO_LARGE", "The request body is too large.")
    return bytes(body)


def _query[T: BaseModel](model: type[T], request: Request) -> T:
    """Query parameters validated with the same strict JSON rules as bodies."""
    params = request.query_params
    if any(len(params.getlist(key)) > 1 for key in params):
        raise ApiProblem("VALIDATION_FAILED", "Each query parameter may appear once.")
    try:
        return model.model_validate_json(json.dumps(dict(params)))
    except ValidationError as exc:
        raise validation_problem(exc, ("query",)) from exc


def create_app(
    settings: Settings,
    *,
    catalog: Callable[[Settings], Catalog] = Catalog.load,
    extra_hosts: frozenset[str] = frozenset(),
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        private_directory(settings.database.parent)
        metadata = Metadata(settings.database)
        service = Service(settings, metadata, catalog(settings))
        service.start()
        app.state.service = service
        try:
            yield
        finally:
            service.stop()
            metadata.close()

    app = FastAPI(
        title="Hachi API",
        version=settings.git_sha[:12],
        description="docs/CONTRACTS.md API surface; types in @hachi/contracts.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Request-Id"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(_Guard, allowed_hosts=LOOPBACK_HOSTS | extra_hosts)

    def service(request: Request) -> Service:
        return request.app.state.service

    @app.exception_handler(ApiProblem)
    async def api_problem(request: Request, exc: ApiProblem) -> Response:
        return _error(request, exc)

    @app.exception_handler(RequestValidationError)
    async def request_invalid(request: Request, exc: RequestValidationError) -> Response:
        return _error(request, ApiProblem("VALIDATION_FAILED", "The request is malformed."))

    @app.exception_handler(HTTPException)
    async def http_problem(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 405:
            problem = ApiProblem(
                "NOT_FOUND", "This endpoint does not take that method.", status=405
            )
        elif exc.status_code == 404:
            problem = ApiProblem("NOT_FOUND", "No such endpoint.")
        else:
            problem = ApiProblem("VALIDATION_FAILED", "The request was refused.", status=400)
        return _error(request, problem)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> Response:
        log.error("unhandled %s during %s request", type(exc).__name__, request.method)
        return _error(request, ApiProblem("INTERNAL_ERROR", "Something went wrong."))

    errors: dict[int | str, dict[str, Any]] = {
        code: {"model": ApiError} for code in (400, 404, 409, 413, 415, 422, 500)
    }

    def documented(model: type[BaseModel], status: int = 200) -> dict[int | str, dict[str, Any]]:
        return {status: {"model": model}, **errors}

    @app.post("/v1/imports", responses=documented(ImportStatus, 202))
    async def create_import(request: Request) -> Response:
        params = _query(UploadParams, request)
        media = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if media not in UPLOAD_TYPES:
            raise ApiProblem(
                "VALIDATION_FAILED",
                "Send the export as the raw body with a zip, xml or octet-stream type.",
                status=415,
            )
        length = request.headers.get("content-length")
        status, created = await service(request).receive_import(
            params, int(length) if length and length.isdigit() else None, request.stream()
        )
        return _json(status, 202 if created else 200)

    @app.get("/v1/imports/{import_id}", responses=documented(ImportStatus))
    def get_import(import_id: str, request: Request) -> Response:
        return _json(service(request).get_import(path_id(import_id, "import_id")))

    @app.get("/v1/subjects/{subject_id}/coverage", responses=documented(Coverage))
    def get_coverage(subject_id: str, request: Request) -> Response:
        subject = path_id(subject_id, "subject_id", subject=True)
        return _json(service(request).coverage(subject, _query(CoverageParams, request)))

    @app.post("/v1/reports", responses=documented(ReportJob, 202))
    async def create_report(request: Request) -> Response:
        body = parse_body(ReportRequest, await _json_body(request))
        job, created = service(request).submit_report(body)
        return _json(job, 202 if created else 200)

    @app.get("/v1/reports/{report_id}", responses=documented(ReportJob))
    def get_report(report_id: str, request: Request) -> Response:
        return _json(service(request).get_report(path_id(report_id, "report_id")))

    @app.post("/v1/subjects/{subject_id}/observations", responses=documented(SelfReportRequest))
    async def add_observations(subject_id: str, request: Request) -> Response:
        subject = path_id(subject_id, "subject_id", subject=True)
        body = parse_body(SelfReportRequest, await _json_body(request))
        stored, created = service(request).add_self_reports(subject, body)
        return _json(stored, 201 if created else 200)

    @app.get("/v1/subjects/{subject_id}/observations", responses=documented(SelfReportHistory))
    def get_observations(subject_id: str, request: Request) -> Response:
        subject = path_id(subject_id, "subject_id", subject=True)
        params = _query(HistoryParams, request)
        return _json(service(request).self_report_history(subject, params))

    @app.delete(
        "/v1/subjects/{subject_id}/observations/{entry_id}", status_code=204, responses=errors
    )
    def delete_observation(subject_id: str, entry_id: str, request: Request) -> Response:
        subject = path_id(subject_id, "subject_id", subject=True)
        entry = path_id(entry_id, "entry_id")
        service(request).delete_self_report(subject, entry, request.query_params.get("confirm"))
        return Response(status_code=204)

    @app.post("/v1/scenarios", responses=documented(ReportResult))
    async def run_scenario(request: Request) -> Response:
        body = parse_body(ScenarioRequest, await _json_body(request))
        return _json(service(request).scenario(body))

    @app.delete("/v1/subjects/{subject_id}", status_code=204, responses=errors)
    def delete_subject(subject_id: str, request: Request) -> Response:
        subject = path_id(subject_id, "subject_id", subject=True)
        service(request).delete_subject(subject, request.query_params.get("confirm"))
        return Response(status_code=204)

    @app.get("/healthz", responses=documented(HealthStatus))
    def health(request: Request) -> Response:
        return _json(service(request).health())

    return app
