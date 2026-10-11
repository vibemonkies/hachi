"""Every non-2xx response is an ApiError with a stable code and the request's id."""

import json
from typing import Any

from pydantic import TypeAdapter, ValidationError

from hachi.contracts.api import ApiError, ApiErrorCode, FieldIssue
from hachi.contracts.base import SCHEMA_VERSION, Identifier, SubjectId

STATUS: dict[ApiErrorCode, int] = {
    "VALIDATION_FAILED": 422,
    "SCHEMA_VERSION_UNSUPPORTED": 400,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "PAYLOAD_TOO_LARGE": 413,
    "INTERNAL_ERROR": 500,
}


class ApiProblem(Exception):
    def __init__(
        self,
        code: ApiErrorCode,
        message: str,
        *,
        issues: list[FieldIssue] | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.issues = issues or []
        self.status = status or STATUS[code]

    def document(self, request_id: str) -> ApiError:
        return ApiError(
            schema_version=SCHEMA_VERSION,
            error_code=self.code,
            message=self.message,
            request_id=request_id,
            field_issues=self.issues[:50],
        )


def _issue(location: tuple, message: str) -> FieldIssue:
    path = ".".join(str(part) for part in location) or "body"
    return FieldIssue(path=path[:200], message=(message or "invalid")[:2000])


# These built-in messages describe fixed schema constraints, never submitted values.
# Other types (especially custom value/assertion/tag errors) remain generic.
_SAFE_RULE_MESSAGES = frozenset(
    {
        "missing",
        "extra_forbidden",
        "literal_error",
        "string_type",
        "int_type",
        "float_type",
        "bool_type",
        "list_type",
        "dict_type",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "string_too_short",
        "string_too_long",
        "string_pattern_mismatch",
    }
)


def validation_problem(error: ValidationError, prefix: tuple = ()) -> ApiProblem:
    """Field issues name the location and rule only; submitted values are never echoed."""
    issues = []
    for issue in error.errors(include_input=False, include_context=False):
        location = tuple(issue["loc"])
        # Extra field names are user input too. Contract-generated locations are safe;
        # drop the untrusted key for extra_forbidden instead of echoing it as a path.
        if issue["type"] == "extra_forbidden":
            location = location[:-1]
        message = (
            issue["msg"]
            if issue["type"] in _SAFE_RULE_MESSAGES
            else "Invalid value for this field or contract rule."
        )
        issues.append(_issue(prefix + location, message))
    return ApiProblem(
        "VALIDATION_FAILED", "The request does not match the contract.", issues=issues
    )


def parse_body[T](adapter: TypeAdapter[T] | type, body: bytes) -> T:
    """Strict JSON validation with the contract's own rules, plus a clear version error."""
    try:
        document: Any = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiProblem(
            "VALIDATION_FAILED", "The body is not valid JSON.", issues=[_issue(("body",), "")]
        ) from exc
    version = document.get("schema_version") if isinstance(document, dict) else None
    if version not in (None, SCHEMA_VERSION):
        raise ApiProblem(
            "SCHEMA_VERSION_UNSUPPORTED",
            f"This API speaks contract schema_version {SCHEMA_VERSION}.",
            issues=[_issue(("body", "schema_version"), f"expected {SCHEMA_VERSION}")],
        )
    try:
        if isinstance(adapter, TypeAdapter):
            return adapter.validate_json(body)
        return adapter.model_validate_json(body)
    except ValidationError as exc:
        raise validation_problem(exc, ("body",)) from exc


_IDENTIFIER = TypeAdapter(Identifier)
_SUBJECT = TypeAdapter(SubjectId)


def path_id(value: str, label: str, *, subject: bool = False) -> str:
    """Ids from the URL are opaque tokens; anything path-like is refused before any lookup."""
    try:
        return (_SUBJECT if subject else _IDENTIFIER).validate_python(value)
    except ValidationError as exc:
        raise ApiProblem(
            "VALIDATION_FAILED",
            f"{label} is not a valid id.",
            issues=[_issue((label,), "letters, digits, '_' and '-' only")],
        ) from exc
