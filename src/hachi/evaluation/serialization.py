"""Stable JSON identities for canonical manifests and internal evaluation artifacts."""

import hashlib
import json
from dataclasses import fields, is_dataclass
from datetime import datetime

from pydantic import BaseModel


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    raise TypeError(f"cannot serialize {type(value).__name__}")


def document_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value, default=_json_default, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode()


def document_sha256(value: object) -> str:
    return hashlib.sha256(document_bytes(value)).hexdigest()
