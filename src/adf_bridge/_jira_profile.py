"""Small shared policy helpers for the v0.1 Jira/GFM profile."""

from __future__ import annotations

from collections.abc import Iterable

from ._errors import AdfConversionError
from ._types import Diagnostic

TABLE_CELL_BREAK = "<br>"
TABLE_CELL_BLOCK_TYPES = frozenset({"paragraph"})
BLOCKQUOTE_CHILD_TYPES = frozenset(
    {"paragraph", "orderedList", "bulletList", "codeBlock", "mediaSingle"}
)
FATAL_BLOCK_MARK_TYPES = frozenset({"alignment", "indentation"})
MEDIA_CONTEXT_TYPES = frozenset({"media", "mediaSingle", "mediaGroup"})


def trailing_hard_break_start(content: list[dict[str, object]]) -> int:
    """Return the first index in a semantically terminal hard-break run."""

    index = len(content)
    while index and content[index - 1].get("type") == "hardBreak":
        index -= 1
    return index


def is_whitespace_only_text_content(content: list[dict[str, object]]) -> bool:
    """Whether nonempty inline content consists entirely of Unicode whitespace."""

    return bool(content) and all(
        child.get("type") == "text"
        and isinstance(text := child.get("text"), str)
        and (not text or text.isspace())
        for child in content
    )


def is_empty_or_whitespace_only_quote_content(content: list[dict[str, object]]) -> bool:
    """Whether quote content has no visible portable GFM representation."""

    semantic_content = [child for child in content if child.get("type") != "hardBreak"]
    return not semantic_content or is_whitespace_only_text_content(semantic_content)


def pointer(path: Iterable[str | int]) -> str:
    """Return an RFC 6901 JSON Pointer for ``path``."""

    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
    return "" if not parts else "/" + "/".join(parts)


def validate_mention_id(
    value: object, *, path: Iterable[str | int] | None = None
) -> str:
    """Return an opaque Jira mention ID or reject unrepresentable syntax."""

    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or any(character.isspace() or character in "\\]" for character in value)
    ):
        raise AdfConversionError(
            "mention ID cannot be represented in Jira mention syntax",
            path="" if path is None else pointer(path),
        )
    return value


def discarded_attributes(
    attrs: dict[str, object],
    *,
    allowed: set[str],
    path: tuple[str | int, ...],
    preserved: set[str] | None = None,
) -> tuple[Diagnostic, ...]:
    """Diagnose supported profile metadata and reject unreviewed attributes."""

    retained = set() if preserved is None else preserved
    diagnostics: list[Diagnostic] = []
    for name in sorted(attrs):
        if name not in allowed:
            raise AdfConversionError(
                f"attribute {name!r} is outside the Jira/GFM profile",
                path=pointer((*path, name)),
            )
        if name not in retained:
            diagnostics.append(
                Diagnostic(
                    code="adf.attribute_discarded",
                    severity="warning",
                    message=(
                        f"ADF attribute {name!r} cannot be represented in portable GFM"
                    ),
                    path=pointer((*path, name)),
                )
            )
    return tuple(diagnostics)
