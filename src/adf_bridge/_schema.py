"""Loading and validating the fixed, bundled Atlassian ADF schema."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from functools import lru_cache
from importlib import resources
from typing import cast

import fastjsonschema

from ._errors import AdfSchemaError, AdfValidationError
from ._jira_profile import pointer
from ._types import AdfDocument

_DATA_PACKAGE = "adf_bridge"
_SCHEMA_NAME = "adf-schema.json"
_PROVENANCE_NAME = "schema-provenance.json"


def _resource_text(name: str) -> str:
    try:
        return (
            resources.files(_DATA_PACKAGE)
            .joinpath("data", name)
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise AdfSchemaError(
            f"bundled ADF schema resource {name!r} is unavailable"
        ) from exc


def _assert_local_refs(value: object) -> None:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if reference is not None and (
            not isinstance(reference, str) or not reference.startswith("#")
        ):
            raise AdfSchemaError("bundled ADF schema contains a non-local $ref")
        for child in value.values():
            _assert_local_refs(child)
    elif isinstance(value, list):
        for child in value:
            _assert_local_refs(child)


@lru_cache(maxsize=1)
def _load_schema() -> dict[str, object]:
    """Read and verify the reviewed package resource once."""

    schema_text = _resource_text(_SCHEMA_NAME)
    try:
        provenance = json.loads(_resource_text(_PROVENANCE_NAME))
    except json.JSONDecodeError as exc:
        raise AdfSchemaError("bundled schema provenance is invalid JSON") from exc
    expected = provenance.get("sha256") if isinstance(provenance, dict) else None
    actual = hashlib.sha256(schema_text.encode("utf-8")).hexdigest()
    if not isinstance(expected, str) or actual != expected:
        raise AdfSchemaError(
            "bundled ADF schema checksum does not match its provenance"
        )
    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as exc:
        raise AdfSchemaError("bundled ADF schema is invalid JSON") from exc
    if not isinstance(schema, dict):
        raise AdfSchemaError("bundled ADF schema root is not an object")
    _assert_local_refs(schema)
    return cast(dict[str, object], schema)


@lru_cache(maxsize=1)
def _validator() -> Callable[[object], object]:
    """Compile the trusted schema once without applying schema defaults."""

    try:
        return cast(
            Callable[[object], object],
            fastjsonschema.compile(
                _load_schema(), use_default=False, detailed_exceptions=True
            ),
        )
    except fastjsonschema.JsonSchemaDefinitionException as exc:
        raise AdfSchemaError("bundled ADF schema cannot be compiled") from exc
    except (MemoryError, RecursionError, TypeError, ValueError) as exc:
        raise AdfSchemaError("bundled ADF schema cannot be compiled") from exc


_MAX_JSON_DEPTH = 100


def _ensure_json(
    value: object,
    path: tuple[str | int, ...] = (),
    active_containers: set[int] | None = None,
) -> None:
    """Reject non-JSON, cyclic, and hostile-depth values before schema validation."""

    if len(path) > _MAX_JSON_DEPTH:
        raise AdfValidationError(
            "ADF nesting exceeds the supported depth",
            path=pointer(path),
            keyword="type",
        )
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
        raise AdfValidationError(
            "ADF contains a non-finite number", path=pointer(path), keyword="type"
        )
    if isinstance(value, (list, dict)):
        active = set() if active_containers is None else active_containers
        identity = id(value)
        if identity in active:
            raise AdfValidationError(
                "ADF contains a cyclic value", path=pointer(path), keyword="type"
            )
        active.add(identity)
        try:
            if isinstance(value, list):
                for index, child in enumerate(value):
                    _ensure_json(child, (*path, index), active)
            else:
                for key, child in value.items():
                    if not isinstance(key, str):
                        raise AdfValidationError(
                            "ADF object keys must be strings",
                            path=pointer(path),
                            keyword="type",
                        )
                    _ensure_json(child, (*path, key), active)
        finally:
            active.remove(identity)
        return
    raise AdfValidationError(
        "ADF must contain only JSON-compatible values",
        path=pointer(path),
        keyword="type",
    )


def _exception_path(path: Sequence[object]) -> str:
    parts = list(path)
    if parts[:1] == ["data"]:
        parts = parts[1:]
    return pointer(cast(list[str | int], parts))


def validate_adf(document: AdfDocument) -> None:
    """Validate ``document`` against the fixed official ADF Draft 4 schema.

    The input is inspected but never normalized or mutated.
    """

    _ensure_json(document)
    try:
        _validator()(document)
    except fastjsonschema.JsonSchemaValueException as exc:
        rule = getattr(exc, "rule", None)
        path = _exception_path(getattr(exc, "path", ()))
        raise AdfValidationError(
            f"ADF fails schema validation ({rule or 'unknown rule'})",
            path=path,
            keyword=rule if isinstance(rule, str) else None,
        ) from exc
    except fastjsonschema.JsonSchemaDefinitionException as exc:
        raise AdfSchemaError("bundled ADF schema cannot validate documents") from exc
    except RecursionError as exc:
        raise AdfValidationError(
            "ADF nesting exceeds the supported depth", keyword="type"
        ) from exc
