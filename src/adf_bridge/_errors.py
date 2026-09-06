"""Project-owned exception contracts."""

from __future__ import annotations

from collections.abc import Iterable

from ._types import Diagnostic


class AdfBridgeError(Exception):
    """Base class for errors raised by adf-bridge."""


class AdfSchemaError(AdfBridgeError):
    """The bundled, trusted ADF schema could not be used."""


class AdfValidationError(AdfBridgeError):
    """A value does not conform to the bundled ADF JSON Schema."""

    def __init__(
        self,
        message: str,
        *,
        path: str = "",
        keyword: str | None = None,
        schema_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.keyword = keyword
        self.schema_path = schema_path


class AdfConversionError(AdfBridgeError):
    """A valid value is outside the focused Jira/GFM conversion profile."""

    def __init__(self, message: str, *, path: str = "") -> None:
        super().__init__(message)
        self.path = path


class LossyConversionError(AdfBridgeError):
    """Strict conversion rejected warnings that non-strict conversion returns."""

    def __init__(self, diagnostics: Iterable[Diagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        super().__init__("conversion would be lossy")
