"""A focused pure-Python bridge between Markdown and Jira ADF."""

from importlib.metadata import version

from ._errors import (
    AdfBridgeError,
    AdfConversionError,
    AdfSchemaError,
    AdfValidationError,
    JiraMediaVerificationError,
    LossyConversionError,
)
from ._markdown import markdown_image_urls, markdown_to_adf
from ._renderer import adf_to_markdown
from ._schema import validate_adf
from ._types import (
    AdfDocument,
    ConversionResult,
    Diagnostic,
    JsonValue,
    ResolvedJiraImage,
)
from ._verification import verify_jira_media_readback

__version__ = version("adf-bridge")

__all__ = [
    "AdfBridgeError",
    "AdfConversionError",
    "AdfDocument",
    "AdfSchemaError",
    "AdfValidationError",
    "ConversionResult",
    "Diagnostic",
    "JiraMediaVerificationError",
    "JsonValue",
    "LossyConversionError",
    "ResolvedJiraImage",
    "adf_to_markdown",
    "markdown_image_urls",
    "markdown_to_adf",
    "validate_adf",
    "verify_jira_media_readback",
]
