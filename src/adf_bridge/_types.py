"""Public value types for adf-bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeAlias, TypeVar

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
AdfDocument: TypeAlias = dict[str, JsonValue]

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A stable machine-readable conversion or validation observation."""

    code: str
    severity: Literal["warning", "error"]
    message: str
    path: str | None = None
    keyword: str | None = None
    schema_path: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedJiraImage:
    """Caller-resolved Jira identity with optional intrinsic image dimensions."""

    source_url: str
    media_id: str
    collection: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class ConversionResult(Generic[T]):
    """A converted value and any readable-degradation warnings."""

    value: T
    diagnostics: tuple[Diagnostic, ...] = ()
