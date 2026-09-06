"""Project-owned recursive serializer from Jira-profile ADF to portable GFM."""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from ._errors import AdfConversionError, LossyConversionError
from ._jira_profile import (
    FATAL_BLOCK_MARK_TYPES,
    MEDIA_CONTEXT_TYPES,
    TABLE_CELL_BLOCK_TYPES,
    TABLE_CELL_BREAK,
    discarded_attributes,
    is_empty_or_whitespace_only_quote_content,
    pointer,
    trailing_hard_break_start,
    validate_mention_id,
)
from ._schema import validate_adf
from ._types import AdfDocument, ConversionResult, Diagnostic

_MARK_ORDER = ("link", "strike", "strong", "em", "code")
_DROPPED_MARKS = {"backgroundColor", "textColor", "underline", "subsup"}
_SAFE_CODE_LANGUAGE = re.compile(r"[^\s`<>\x00-\x1f\x7f]+")
_BARE_URL_SCHEME = re.compile(r"https?://")
_CODE_LINE_ENDING = re.compile(r"\r\n?|\n")
_COMMONMARK_TRIMMED_WHITESPACE = frozenset(" \t\r\n")
_PRESENTATION_DELIMITER_MARKS = frozenset({"em", "strong", "strike"})
_LABEL_ENTITIES = {
    "\\": "&#92;",
    "`": "&#96;",
    "*": "&#42;",
    "_": "&#95;",
    "[": "&#91;",
    "]": "&#93;",
    "~": "&#126;",
    "|": "&#124;",
}
_DESTINATION_SOURCE_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~:/?#@!$'()*+,;=%"
)


@dataclass(frozen=True, slots=True)
class _LiteralContext:
    table_cell: bool
    block_start: bool
    suppress_bare_urls: bool = True
    label: bool = False


@dataclass(frozen=True, slots=True)
class _InlineFragment:
    """A renderer-local inline emission with optional source-edge encoding."""

    render: Callable[[bool, bool], str] | None
    can_encode_left_edge: bool
    can_encode_right_edge: bool
    is_inline: bool = True
    text: str | None = None
    marks: tuple[_NormalizedMark, ...] = ()
    context: _LiteralContext | None = None
    source_encoded: frozenset[int] = frozenset()


@dataclass
class _RenderState:
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def warn(self, code: str, message: str, path: tuple[str | int, ...]) -> None:
        self.diagnostics.append(Diagnostic(code, "warning", message, pointer(path)))

    def discard(
        self,
        attrs: dict[str, object],
        allowed: set[str],
        path: tuple[str | int, ...],
        preserved: set[str] | None = None,
    ) -> None:
        self.diagnostics.extend(
            discarded_attributes(attrs, allowed=allowed, path=path, preserved=preserved)
        )


def _normalize_nul_text(
    text: str, state: _RenderState, path: tuple[str | int, ...]
) -> str:
    """Apply CommonMark's required NUL replacement to visible text."""

    if "\x00" not in text:
        return text
    state.warn(
        "adf.nul_normalized",
        "ADF text U+0000 is normalized to U+FFFD by CommonMark",
        path,
    )
    return text.replace("\x00", "\ufffd")


def _attrs(node: dict[str, object]) -> dict[str, object]:
    attrs = node.get("attrs", {})
    if not isinstance(attrs, dict):  # Schema validation makes this defensive only.
        raise AdfConversionError("ADF node attrs must be an object")
    return cast(dict[str, object], attrs)


def _content(node: dict[str, object]) -> list[dict[str, object]]:
    content = node.get("content", [])
    if not isinstance(content, list):
        raise AdfConversionError("ADF node content must be an array")
    return [cast(dict[str, object], child) for child in content]


def _can_encode_source_edge(text: str, index: int) -> bool:
    """Whether a numeric character reference preserves this exact source value."""

    character = text[index]
    return html.unescape(f"&#{ord(character)};") == character


def _is_unrepresentable_delimiter_whitespace(character: str) -> bool:
    """Whether Mistune treats this non-CommonMark boundary as whitespace."""

    return (
        character.isspace()
        and character not in _COMMONMARK_TRIMMED_WHITESPACE
        and not _can_encode_source_edge(character, 0)
    )


def _is_representable_delimiter_whitespace(character: str) -> bool:
    return (
        character.isspace()
        and character not in _COMMONMARK_TRIMMED_WHITESPACE
        and _can_encode_source_edge(character, 0)
    )


def _protect_container_boundary_whitespace(
    text: str,
    state: _RenderState,
    path: tuple[str | int, ...],
    *,
    owner: str | None,
    left_edge: bool,
    right_edge: bool,
    diagnose_left_source_line_boundary: bool = False,
    diagnose_right_source_line_boundary: bool = False,
) -> frozenset[int]:
    """Source-encode whitespace that a list or table would otherwise trim."""

    if not text:
        return frozenset()
    encoded: set[int] = set()
    normalized = False
    source_line_boundary_whitespace = False
    for index, edge, diagnose_source_line_boundary in (
        (0, left_edge, diagnose_left_source_line_boundary),
        (len(text) - 1, right_edge, diagnose_right_source_line_boundary),
    ):
        if not edge:
            continue
        character = text[index]
        if not character.isspace() or character in _COMMONMARK_TRIMMED_WHITESPACE:
            continue
        if _can_encode_source_edge(text, index):
            encoded.add(index)
            source_line_boundary_whitespace |= diagnose_source_line_boundary
        else:
            normalized = True
    if normalized or source_line_boundary_whitespace:
        state.warn(
            "adf.boundary_whitespace_normalized",
            "non-CommonMark boundary whitespace requires context-sensitive "
            f"source encoding or normalization in this {owner}",
            path,
        )
    return frozenset(encoded)


def _escape_characters(
    text: str,
    *,
    table_cell: bool,
    label: bool = False,
    source_encoded: frozenset[int] = frozenset(),
    force_escaped: frozenset[int] = frozenset(),
) -> str:
    leading = 0
    while leading < len(text) and text[leading] in _COMMONMARK_TRIMMED_WHITESPACE:
        leading += 1
    trailing = len(text)
    while trailing > leading and text[trailing - 1] in _COMMONMARK_TRIMMED_WHITESPACE:
        trailing -= 1

    escaped_parts: list[str] = []
    for index, character in enumerate(text):
        if (
            index in source_encoded
            or index < leading
            or index >= trailing
            or character in {"\r", "\n", "\f"}
        ):
            escaped_parts.append(f"&#{ord(character)};")
            continue
        if label and character in _LABEL_ENTITIES:
            escaped_parts.append(_LABEL_ENTITIES[character])
            continue
        rendered = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            "\\": "\\\\",
            "`": "\\`",
            "*": "\\*",
            "_": "\\_",
            "[": "\\[",
            "]": "\\]",
            "~": "\\~",
            "|": "\\|" if table_cell else "|",
        }.get(character, character)
        escaped_parts.append("\\" + rendered if index in force_escaped else rendered)
    return "".join(escaped_parts)


def _source_encode_heading_closing_hashes(markdown: str) -> str:
    """Keep a literal ATX closing-hash candidate in heading text."""

    return re.sub(
        r"(?:^|(?<=[ \t]))\\?(#+)$",
        lambda match: "&#35;" * len(match[1]),
        markdown,
    )


def _escape_block_start(
    line: str,
    *,
    table_cell: bool,
    source_encoded: frozenset[int] = frozenset(),
) -> str:
    """Escape literal text where Markdown accepts a block."""

    forced_escape: frozenset[int] = frozenset()
    if re.match(r"^(?: {4}| {0,3}\t)", line):
        source_encoded = source_encoded | frozenset({0})
    else:
        indent = re.match(r"^ {0,3}", line)
        assert indent is not None  # A regular expression with a zero-length match.
        prefix = indent.group()
        remainder = line[len(prefix) :]
        ordered = re.match(r"\d{1,9}[.)]", remainder)
        if ordered:
            forced_escape = frozenset({len(prefix) + ordered.end() - 1})
        elif remainder.startswith(("#", "+", "-")) or re.fullmatch(
            r"[=-]+[ \t]*", remainder
        ):
            forced_escape = frozenset({len(prefix)})
    return _escape_characters(
        line,
        table_cell=table_cell,
        source_encoded=source_encoded,
        force_escaped=forced_escape,
    )


def _emit_literal(
    text: str,
    context: _LiteralContext,
    *,
    encode_left_edge: bool = False,
    encode_right_edge: bool = False,
    source_encoded: frozenset[int] = frozenset(),
) -> str:
    """Emit text losslessly without relying on Markdown layout or HTML parsing."""

    source_encoded = source_encoded | frozenset(
        index
        for index, enabled in (
            (0, encode_left_edge),
            (len(text) - 1, encode_right_edge),
        )
        if enabled and text
    )
    if context.block_start:
        rendered = _escape_block_start(
            text, table_cell=context.table_cell, source_encoded=source_encoded
        )
    else:
        rendered = _escape_characters(
            text,
            table_cell=context.table_cell,
            label=context.label,
            source_encoded=source_encoded,
        )
    if context.suppress_bare_urls:
        rendered = _protect_bare_urls(rendered)
    return rendered


def _emit_label(
    text: str,
    *,
    table_cell: bool,
    encode_left_edge: bool = False,
    encode_right_edge: bool = False,
) -> str:
    """Emit source text inside a Markdown link or image label."""

    return _emit_literal(
        text,
        _LiteralContext(table_cell, False, suppress_bare_urls=False, label=True),
        encode_left_edge=encode_left_edge,
        encode_right_edge=encode_right_edge,
    )


def _protect_bare_urls(text: str) -> str:
    """Prevent the Markdown URL extension from adding an ADF link mark."""

    return _BARE_URL_SCHEME.sub(lambda match: match[0].replace(":", "&#58;"), text)


def _inline_fence_parts(text: str, *, table_cell: bool) -> tuple[str, str, str]:
    """Return the opening fence, content, and closing fence for a code span."""

    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    content = text.replace("|", r"\|") if table_cell else text
    if content.strip() and (
        content.startswith((" ", "`")) or content.endswith((" ", "`"))
    ):
        return f"{fence} ", content, f" {fence}"
    return fence, content, fence


def _block_fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _validate_destination(destination: str, path: tuple[str | int, ...]) -> None:
    """Reject destination characters that HTML entities cannot preserve exactly."""

    for character in destination:
        if html.unescape(f"&#{ord(character)};") != character:
            raise AdfConversionError(
                "ADF destination contains a character that cannot round-trip "
                "through portable GFM",
                path=pointer(path),
            )


def _encode_destination(destination: str) -> str:
    """Encode an opaque destination without URL normalization."""

    return "".join(
        character if character in _DESTINATION_SOURCE_SAFE else f"&#{ord(character)};"
        for character in destination
    )


def _source_encode_table_pipe(value: str, *, table_cell: bool) -> str:
    """Keep syntax-owned values from becoming GFM table delimiters."""

    return value.replace("|", "&#124;") if table_cell else value


def _link_destination(href: str, title: object, *, table_cell: bool) -> str:
    result = f"<{_encode_destination(href)}>"
    if isinstance(title, str):
        escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
        encoded_title = _source_encode_table_pipe(
            escaped_title.replace("&", "&amp;"), table_cell=table_cell
        )
        result += f' "{encoded_title}"'
    return result


def _has_unsafe_link_title_control(title: str) -> bool:
    """Whether a Markdown title cannot preserve one of its control characters."""

    return any(unicodedata.category(character) == "Cc" for character in title)


_NormalizedMark = tuple[str, str | None, str | None]


def _normalized_marks(
    marks: object, state: _RenderState, path: tuple[str | int, ...]
) -> tuple[_NormalizedMark, ...]:
    if not isinstance(marks, list):
        raise AdfConversionError("ADF text marks must be an array", path=pointer(path))
    seen: set[str] = set()
    retained: dict[str, _NormalizedMark] = {}
    for index, mark_value in enumerate(marks):
        if not isinstance(mark_value, dict):
            raise AdfConversionError(
                "ADF mark must be an object", path=pointer((*path, index))
            )
        mark = cast(dict[str, object], mark_value)
        mark_type = mark.get("type")
        if not isinstance(mark_type, str):
            raise AdfConversionError(
                "ADF mark has no type", path=pointer((*path, index))
            )
        if mark_type in seen:
            raise AdfConversionError(
                f"duplicate {mark_type!r} marks are outside the profile",
                path=pointer((*path, index)),
            )
        seen.add(mark_type)
        attrs = _attrs(mark)
        if mark_type in _DROPPED_MARKS:
            state.warn(
                "adf.mark_discarded",
                f"ADF {mark_type!r} mark cannot be represented in portable GFM",
                (*path, index),
            )
            state.discard(attrs, set(attrs), (*path, index, "attrs"))
            continue
        if mark_type not in _MARK_ORDER:
            raise AdfConversionError(
                f"ADF mark {mark_type!r} is outside the Jira/GFM profile",
                path=pointer((*path, index)),
            )
        if mark_type == "link":
            href = attrs.get("href")
            if not isinstance(href, str) or not href:
                raise AdfConversionError(
                    "link mark has no usable href", path=pointer((*path, index))
                )
            _validate_destination(href, (*path, index, "attrs", "href"))
            title = attrs.get("title")
            discard_title = title == "" or (
                isinstance(title, str) and _has_unsafe_link_title_control(title)
            )
            state.discard(
                attrs,
                {"href", "title", "collection", "id", "occurrenceKey"},
                (*path, index, "attrs"),
                preserved={"href"} if discard_title else {"href", "title"},
            )
            if discard_title:
                title = None
            retained[mark_type] = (
                mark_type,
                href,
                title if isinstance(title, str) else None,
            )
        elif attrs:
            raise AdfConversionError(
                f"ADF {mark_type!r} mark attributes are outside the profile",
                path=pointer((*path, index, "attrs")),
            )
        else:
            retained[mark_type] = (mark_type, None, None)
    return tuple(
        retained[mark_type] for mark_type in _MARK_ORDER if mark_type in retained
    )


def _render_marked_text(
    text: str,
    marks: tuple[_NormalizedMark, ...],
    context: _LiteralContext,
    *,
    encode_left_edge: bool = False,
    encode_right_edge: bool = False,
    source_encoded: frozenset[int] = frozenset(),
) -> str:
    """Render a text span after its surrounding marks have been opened."""

    mark_types = {mark[0] for mark in marks}
    if "code" in mark_types:
        return text.replace("|", r"\|") if context.table_cell else text
    presentation_delimiters = mark_types & _PRESENTATION_DELIMITER_MARKS
    encode_left_delimiter_whitespace = bool(
        text
        and presentation_delimiters
        and _is_representable_delimiter_whitespace(text[0])
    )
    encode_right_delimiter_whitespace = bool(
        text
        and presentation_delimiters
        and _is_representable_delimiter_whitespace(text[-1])
    )
    return _emit_literal(
        text,
        _LiteralContext(
            context.table_cell,
            False if "link" in mark_types else context.block_start,
            suppress_bare_urls="link" not in mark_types,
            label="link" in mark_types,
        ),
        encode_left_edge=encode_left_edge or encode_left_delimiter_whitespace,
        encode_right_edge=encode_right_edge or encode_right_delimiter_whitespace,
        source_encoded=source_encoded,
    )


def _open_mark(
    mark: _NormalizedMark, *, text: str, table_cell: bool
) -> tuple[str, str | None]:
    mark_type, href, _title = mark
    if mark_type == "link":
        if href is None:  # Defensive: _normalized_marks requires a non-empty href.
            raise AdfConversionError("link mark has no usable href")
        return "[", None
    if mark_type == "strike":
        return "~~", None
    if mark_type == "strong":
        return "**", None
    if mark_type == "em":
        return "_", None
    if mark_type == "code":
        opening, _content, closing = _inline_fence_parts(text, table_cell=table_cell)
        return opening, closing
    raise AssertionError(f"unsupported normalized mark {mark_type!r}")


def _close_mark(
    mark: _NormalizedMark, code_closing: str | None, *, table_cell: bool
) -> str:
    mark_type, href, title = mark
    if mark_type == "link":
        if href is None:  # Defensive: _normalized_marks requires a non-empty href.
            raise AdfConversionError("link mark has no usable href")
        return f"]({_link_destination(href, title, table_cell=table_cell)})"
    if mark_type == "strike":
        return "~~"
    if mark_type == "strong":
        return "**"
    if mark_type == "em":
        return "_"
    if mark_type == "code":
        assert code_closing is not None
        return code_closing
    raise AssertionError(f"unsupported normalized mark {mark_type!r}")


def _compose_inline_fragments(
    fragments: list[_InlineFragment], *, table_cell: bool
) -> str:
    """Compose text marks as one local stack across inline fragments."""

    prepared: list[tuple[_InlineFragment, bool, bool]] = []
    pending: _InlineFragment | None = None
    pending_has_left_boundary = False
    for fragment in fragments:
        if pending is None:
            pending = fragment
            continue
        boundary = pending.is_inline and fragment.is_inline
        prepared.append(
            (
                pending,
                pending_has_left_boundary,
                boundary and pending.can_encode_right_edge,
            )
        )
        pending = fragment
        pending_has_left_boundary = boundary and fragment.can_encode_left_edge
    if pending is not None:
        prepared.append((pending, pending_has_left_boundary, False))

    output: list[str] = []
    active_marks: list[_NormalizedMark] = []
    code_closing: str | None = None

    def close_marks(keep: int) -> None:
        nonlocal code_closing
        while len(active_marks) > keep:
            mark = active_marks.pop()
            output.append(_close_mark(mark, code_closing, table_cell=table_cell))
            if mark[0] == "code":
                code_closing = None

    for fragment, encode_left, encode_right in prepared:
        if fragment.text is None:
            close_marks(0)
            assert fragment.render is not None
            output.append(fragment.render(encode_left, encode_right))
            continue
        assert fragment.context is not None
        target_marks = fragment.marks
        common = 0
        while (
            common < len(active_marks)
            and common < len(target_marks)
            and active_marks[common] == target_marks[common]
        ):
            common += 1
        close_marks(common)
        for mark in target_marks[common:]:
            opening, closing = _open_mark(
                mark, text=fragment.text, table_cell=fragment.context.table_cell
            )
            output.append(opening)
            active_marks.append(mark)
            if mark[0] == "code":
                code_closing = closing
        output.append(
            _render_marked_text(
                fragment.text,
                target_marks,
                fragment.context,
                encode_left_edge=encode_left,
                encode_right_edge=encode_right,
                source_encoded=fragment.source_encoded,
            )
        )
    close_marks(0)
    return "".join(output)


def _normalize_code_line_endings(
    text: str, state: _RenderState, path: tuple[str | int, ...]
) -> str:
    if _CODE_LINE_ENDING.search(text):
        state.warn(
            "adf.code_span_line_break_normalized",
            "inline code line endings are normalized to spaces by Markdown",
            path,
        )
        return _CODE_LINE_ENDING.sub(" ", text)
    return text


def _normalize_code_block_text(
    text: str, state: _RenderState, path: tuple[str | int, ...]
) -> str:
    """Canonicalize code-block text to Mistune's fenced-code output."""

    normalized = _CODE_LINE_ENDING.sub("\n", text)
    if normalized and not normalized.endswith("\n"):
        normalized += "\n"
    if normalized != text:
        state.warn(
            "adf.code_block_text_normalized",
            "code block text is normalized to LF with one trailing newline",
            path,
        )
    return normalized


def _render_inline(
    nodes: list[dict[str, object]],
    state: _RenderState,
    path: tuple[str | int, ...],
    *,
    table_cell: bool,
    boundary_owner: str | None = None,
    source_left_edge: bool = False,
    source_right_edge: bool = False,
) -> str:
    fragments: list[_InlineFragment] = []
    pending_text: list[str] = []
    pending_marks: tuple[_NormalizedMark, ...] | None = None
    pending_source_encoded: set[int] = set()
    pending_block_start = False
    at_block_start = True
    terminal_hard_break_start = (
        len(nodes) if table_cell else trailing_hard_break_start(nodes)
    )

    def text_fragment(
        text: str,
        marks: tuple[_NormalizedMark, ...],
        context: _LiteralContext,
        source_encoded: frozenset[int],
    ) -> _InlineFragment:
        return _InlineFragment(
            None,
            can_encode_left_edge=(
                bool(text)
                and not any(mark[0] == "code" for mark in marks)
                and _can_encode_source_edge(text, 0)
            ),
            can_encode_right_edge=(
                bool(text)
                and not any(mark[0] == "code" for mark in marks)
                and _can_encode_source_edge(text, -1)
            ),
            text=text,
            marks=marks,
            context=context,
            source_encoded=source_encoded,
        )

    def literal_fragment(text: str, context: _LiteralContext) -> _InlineFragment:
        return _InlineFragment(
            lambda encode_left, encode_right: _emit_literal(
                text,
                context,
                encode_left_edge=encode_left,
                encode_right_edge=encode_right,
            ),
            can_encode_left_edge=bool(text) and _can_encode_source_edge(text, 0),
            can_encode_right_edge=bool(text) and _can_encode_source_edge(text, -1),
        )

    def rendered_fragment(rendered: str, *, is_inline: bool = True) -> _InlineFragment:
        return _InlineFragment(
            lambda _encode_left, _encode_right: rendered,
            can_encode_left_edge=False,
            can_encode_right_edge=False,
            is_inline=is_inline,
        )

    def flush_text() -> None:
        nonlocal pending_marks
        if pending_marks is not None:
            fragments.append(
                text_fragment(
                    "".join(pending_text),
                    pending_marks,
                    _LiteralContext(table_cell, pending_block_start),
                    frozenset(pending_source_encoded),
                )
            )
        pending_text.clear()
        pending_marks = None
        pending_source_encoded.clear()

    for index, node in enumerate(nodes):
        node_path = (*path, index)
        node_type = node.get("type")
        if node_type == "text":
            text = node.get("text")
            if not isinstance(text, str):
                raise AdfConversionError(
                    "text node has no text", path=pointer(node_path)
                )
            text = _normalize_nul_text(text, state, (*node_path, "text"))
            marks = _normalized_marks(
                node.get("marks", []), state, (*node_path, "marks")
            )
            mark_types = {mark[0] for mark in marks}
            if {"code", "link"} <= mark_types and ("[" in text or "]" in text):
                raise AdfConversionError(
                    "linked code containing brackets cannot round-trip in Markdown",
                    path=pointer((*node_path, "text")),
                )
            if (
                mark_types & _PRESENTATION_DELIMITER_MARKS
                and text
                and (
                    _is_unrepresentable_delimiter_whitespace(text[0])
                    or _is_unrepresentable_delimiter_whitespace(text[-1])
                )
            ):
                state.warn(
                    "adf.presentation_mark_degraded",
                    "ADF presentation marks cannot be represented with this "
                    "boundary whitespace in portable GFM",
                    (*node_path, "marks"),
                )
                marks = tuple(
                    mark
                    for mark in marks
                    if mark[0] not in _PRESENTATION_DELIMITER_MARKS
                )
            if any(mark[0] == "code" for mark in marks):
                text = _normalize_code_line_endings(text, state, (*node_path, "text"))
            left_source_line_boundary = (
                not table_cell
                and index > 0
                and nodes[index - 1].get("type") == "hardBreak"
            )
            right_source_line_boundary = (
                not table_cell
                and index < len(nodes) - 1
                and nodes[index + 1].get("type") == "hardBreak"
            )
            left_edge = (source_left_edge and index == 0) or left_source_line_boundary
            right_edge = (
                source_right_edge and index == len(nodes) - 1
            ) or right_source_line_boundary
            source_encoded = _protect_container_boundary_whitespace(
                text,
                state,
                (*node_path, "text"),
                owner=boundary_owner or "paragraph",
                left_edge=left_edge,
                right_edge=right_edge,
                diagnose_left_source_line_boundary=left_source_line_boundary,
                diagnose_right_source_line_boundary=right_source_line_boundary,
            )
            if pending_marks == marks:
                offset = sum(map(len, pending_text))
                pending_text.append(text)
                pending_source_encoded.update(
                    offset + source_index for source_index in source_encoded
                )
            else:
                flush_text()
                pending_text.append(text)
                pending_marks = marks
                pending_block_start = at_block_start
                pending_source_encoded.update(source_encoded)
            at_block_start = False
            continue

        flush_text()
        if node_type == "hardBreak":
            attrs = _attrs(node)
            state.discard(attrs, {"text", "localId"}, (*node_path, "attrs"))
            if not table_cell and index >= terminal_hard_break_start:
                state.warn(
                    "adf.terminal_hard_break_discarded",
                    "a terminal ADF hard break has no semantic portable GFM "
                    "representation",
                    node_path,
                )
            else:
                fragments.append(
                    rendered_fragment(
                        TABLE_CELL_BREAK if table_cell else "\\\n", is_inline=False
                    )
                )
            at_block_start = not table_cell
        elif node_type == "mention":
            attrs = _attrs(node)
            user_type = attrs.get("userType")
            if user_type in {"SPECIAL", "APP"}:
                raise AdfConversionError(
                    "special and app mentions are outside the user-mention profile",
                    path=pointer(node_path),
                )
            state.discard(
                attrs,
                {"id", "text", "accessLevel", "userType", "localId"},
                (*node_path, "attrs"),
                preserved={"id"},
            )
            mention_id = validate_mention_id(
                attrs.get("id"), path=(*node_path, "attrs", "id")
            )
            encoded_id = _source_encode_table_pipe(
                mention_id.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"),
                table_cell=table_cell,
            )
            fragments.append(rendered_fragment(f"[~accountId:{encoded_id}]"))
            at_block_start = False
        elif node_type == "date":
            attrs = _attrs(node)
            state.warn(
                "adf.date_degraded",
                "ADF date identity is rendered as a UTC ISO date",
                node_path,
            )
            state.discard(
                attrs, {"timestamp", "localId"}, (*node_path, "attrs"), {"timestamp"}
            )
            timestamp = attrs.get("timestamp")
            try:
                if not isinstance(timestamp, str) or not timestamp:
                    raise ValueError
                value = (
                    datetime.fromtimestamp(int(timestamp) / 1000, UTC)
                    .date()
                    .isoformat()
                )
            except (OSError, OverflowError, ValueError):
                raise AdfConversionError(
                    "ADF date timestamp is not a valid millisecond timestamp",
                    path=pointer((*node_path, "attrs", "timestamp")),
                ) from None
            fragments.append(
                literal_fragment(value, _LiteralContext(table_cell, at_block_start))
            )
            at_block_start = False
        elif node_type == "emoji":
            attrs = _attrs(node)
            state.warn(
                "adf.emoji_degraded",
                "ADF emoji metadata cannot be preserved in portable GFM",
                node_path,
            )
            value = attrs.get("text") or attrs.get("shortName")
            if not isinstance(value, str) or not value:
                raise AdfConversionError(
                    "ADF emoji has no readable value", path=pointer(node_path)
                )
            preserved = {"text"} if attrs.get("text") == value else {"shortName"}
            value_path = (
                (*node_path, "attrs", "text")
                if "text" in preserved
                else (*node_path, "attrs", "shortName")
            )
            value = _normalize_nul_text(value, state, value_path)
            state.discard(
                attrs,
                {"shortName", "id", "text", "localId"},
                (*node_path, "attrs"),
                preserved,
            )
            fragments.append(
                literal_fragment(value, _LiteralContext(table_cell, at_block_start))
            )
            at_block_start = False
        elif node_type == "inlineCard":
            attrs = _attrs(node)
            state.warn(
                "adf.inline_card_degraded",
                "ADF inline card is rendered as an ordinary link",
                node_path,
            )
            state.discard(
                attrs,
                {"url", "data", "localId"},
                (*node_path, "attrs"),
                preserved={"url"},
            )
            card_url = attrs.get("url")
            card_url_path = (*node_path, "attrs", "url")
            data = attrs.get("data")
            if not isinstance(card_url, str) and isinstance(data, dict):
                card_url = data.get("url")
                card_url_path = (*node_path, "attrs", "data", "url")
            if not isinstance(card_url, str) or not card_url:
                raise AdfConversionError(
                    "ADF inline card has no usable URL", path=pointer(node_path)
                )
            _validate_destination(card_url, card_url_path)

            def render_card(
                encode_left: bool, encode_right: bool, card_url: str = card_url
            ) -> str:
                label = _emit_label(
                    card_url,
                    table_cell=table_cell,
                    encode_left_edge=encode_left,
                    encode_right_edge=encode_right,
                )
                destination = _link_destination(card_url, None, table_cell=table_cell)
                return f"[{label}]({destination})"

            fragments.append(
                _InlineFragment(
                    render_card,
                    can_encode_left_edge=_can_encode_source_edge(card_url, 0),
                    can_encode_right_edge=_can_encode_source_edge(card_url, -1),
                )
            )
            at_block_start = False
        elif node_type == "status":
            attrs = _attrs(node)
            state.warn(
                "adf.status_degraded",
                "ADF status style is rendered as plain text",
                node_path,
            )
            state.discard(
                attrs,
                {"text", "color", "style", "localId"},
                (*node_path, "attrs"),
                preserved={"text"},
            )
            status_text = attrs.get("text")
            if not isinstance(status_text, str):
                raise AdfConversionError(
                    "ADF status has no text", path=pointer(node_path)
                )
            status_text = _normalize_nul_text(
                status_text, state, (*node_path, "attrs", "text")
            )
            fragments.append(
                literal_fragment(
                    status_text, _LiteralContext(table_cell, at_block_start)
                )
            )
            at_block_start = False
        else:
            raise AdfConversionError(
                f"ADF inline node {node_type!r} is outside the Jira/GFM profile",
                path=pointer(node_path),
            )
    flush_text()
    return _compose_inline_fragments(fragments, table_cell=table_cell)


def _reject_media_marks(node: dict[str, object], path: tuple[str | int, ...]) -> None:
    marks = node.get("marks", [])
    if not isinstance(marks, list):
        raise AdfConversionError("ADF media marks must be an array", path=pointer(path))
    if marks:
        raise AdfConversionError(
            "ADF media marks are outside the Jira/GFM profile",
            path=pointer((*path, "marks", 0)),
        )


def _render_media(
    node: dict[str, object], state: _RenderState, path: tuple[str | int, ...]
) -> str:
    _reject_media_marks(node, path)
    attrs = _attrs(node)
    media_type = attrs.get("type")
    if media_type == "external":
        state.discard(
            attrs,
            {"type", "url", "alt", "height", "width", "localId"},
            (*path, "attrs"),
            preserved={"type", "url", "alt"},
        )
        url = attrs.get("url")
        if not isinstance(url, str) or not url:
            raise AdfConversionError(
                "external media has no usable URL", path=pointer(path)
            )
        _validate_destination(url, (*path, "attrs", "url"))
        alt = attrs.get("alt")
        alt_text = (
            _normalize_nul_text(alt, state, (*path, "attrs", "alt"))
            if isinstance(alt, str)
            else ""
        )
        label = _emit_label(alt_text, table_cell=False)
        return f"![{label}]({_link_destination(url, None, table_cell=False)})"
    if media_type not in {"file", "link"}:
        raise AdfConversionError(
            "ADF media type is outside the profile", path=pointer(path)
        )
    state.warn(
        "adf.media_degraded",
        "managed ADF media is rendered as readable text because its URL is unavailable",
        path,
    )
    alt = attrs.get("alt")
    if isinstance(alt, str):
        alt = _normalize_nul_text(alt, state, (*path, "attrs", "alt"))
    preserved: set[str] = {"alt"} if isinstance(alt, str) and alt else {"id"}
    state.discard(
        attrs,
        {
            "type",
            "id",
            "collection",
            "alt",
            "height",
            "width",
            "occurrenceKey",
            "localId",
        },
        (*path, "attrs"),
        preserved=preserved,
    )
    context = _LiteralContext(table_cell=False, block_start=True)
    if isinstance(alt, str) and alt:
        return _emit_literal(alt, context)
    return "attachment"


def _render_table_cell(
    node: dict[str, object], state: _RenderState, path: tuple[str | int, ...]
) -> str:
    attrs = _attrs(node)
    blocks = _content(node)
    if not blocks or any(
        block.get("type") not in TABLE_CELL_BLOCK_TYPES for block in blocks
    ):
        raise AdfConversionError(
            "only paragraphs are supported inside GFM table cells",
            path=pointer((*path, "content")),
        )
    has_hard_break = any(
        child.get("type") == "hardBreak"
        for paragraph in blocks
        for child in _content(paragraph)
    )
    if len(blocks) > 1 or has_hard_break:
        state.warn(
            "adf.table_cell_flattened",
            "table cell paragraphs and hard breaks are flattened with <br>",
            path,
        )
    state.discard(
        attrs,
        {"background", "colspan", "rowspan", "colwidth", "localId"},
        (*path, "attrs"),
    )
    if len(blocks) == 1 and _is_empty_gfm_paragraph(
        blocks[0], state, (*path, "content", 0)
    ):
        return ""

    rendered: list[str] = []
    for paragraph_index, paragraph in enumerate(blocks):
        paragraph_path = (*path, "content", paragraph_index)
        for child_index, child in enumerate(_content(paragraph)):
            text = child.get("text")
            marks = child.get("marks", [])
            if (
                child.get("type") == "text"
                and isinstance(text, str)
                and re.search(r"\\+\|", text)
                and isinstance(marks, list)
                and any(
                    isinstance(mark, dict) and mark.get("type") == "code"
                    for mark in marks
                )
            ):
                raise AdfConversionError(
                    "code text with a backslash before a pipe is not supported "
                    "in GFM table cells",
                    path=pointer((*paragraph_path, "content", child_index)),
                )
        cell = _render_block(
            paragraph,
            state,
            paragraph_path,
            table_cell=True,
            boundary_owner="table cell",
            source_left_edge=paragraph_index == 0,
            source_right_edge=paragraph_index == len(blocks) - 1,
        )
        if "\r" in cell or "\n" in cell:
            raise AdfConversionError(
                "multi-line content is not supported inside GFM table cells",
                path=pointer(paragraph_path),
            )
        rendered.append(cell)
    return TABLE_CELL_BREAK.join(rendered)


def _render_table(
    node: dict[str, object], state: _RenderState, path: tuple[str | int, ...]
) -> str:
    attrs = _attrs(node)
    state.discard(
        attrs,
        {"displayMode", "isNumberColumnEnabled", "layout", "localId", "width"},
        (*path, "attrs"),
    )
    rows: list[tuple[list[str], list[bool], tuple[str | int, ...]]] = []
    for row_index, row in enumerate(_content(node)):
        row_path = (*path, "content", row_index)
        if row.get("type") != "tableRow":
            raise AdfConversionError(
                "table contains a non-row node", path=pointer(row_path)
            )
        row_attrs = _attrs(row)
        state.discard(row_attrs, {"localId"}, (*row_path, "attrs"))
        cells: list[str] = []
        headers: list[bool] = []
        for cell_index, cell in enumerate(_content(row)):
            cell_type = cell.get("type")
            if cell_type not in {"tableCell", "tableHeader"}:
                raise AdfConversionError(
                    "table row contains a non-cell node", path=pointer(row_path)
                )
            headers.append(cell_type == "tableHeader")
            cells.append(
                _render_table_cell(cell, state, (*row_path, "content", cell_index))
            )
        rows.append((cells, headers, row_path))
    if not rows:
        raise AdfConversionError(
            "empty table is outside the profile", path=pointer(path)
        )
    width = max(len(cells) for cells, _, _ in rows)
    if width == 0:
        raise AdfConversionError(
            "table rows must contain at least one cell", path=pointer(path)
        )

    first_cells, first_headers, _ = rows[0]
    if any(first_headers):
        for cell_index, is_header in enumerate(first_headers):
            if not is_header:
                state.warn(
                    "adf.table_header_normalized",
                    "a first-row data cell is rendered as a GFM header cell",
                    (*path, "content", 0, "content", cell_index),
                )
        header = first_cells
        body_rows = rows[1:]
    else:
        state.warn(
            "adf.table_header_synthesized",
            "table without a header is rendered with an empty GFM header row",
            path,
        )
        header = [""] * width
        body_rows = rows

    normalized_body: list[list[str]] = []
    for cells, headers, row_path in body_rows:
        for cell_index, is_header in enumerate(headers):
            if is_header:
                state.warn(
                    "adf.table_header_normalized",
                    "a non-first-row header cell is rendered as a GFM body cell",
                    (*row_path, "content", cell_index),
                )
        if len(cells) < width:
            state.warn(
                "adf.table_row_padded",
                "short table row is padded for portable GFM",
                row_path,
            )
            cells = [*cells, *([""] * (width - len(cells)))]
        normalized_body.append(cells)
    if len(header) < width:
        state.warn(
            "adf.table_row_padded",
            "short table row is padded for portable GFM",
            (*path, "content", 0),
        )
        header = [*header, *([""] * (width - len(header)))]
    lines = [f"| {' | '.join(header)} |", f"| {' | '.join(['---'] * width)} |"]
    lines.extend(f"| {' | '.join(row)} |" for row in normalized_body)
    return "\n".join(lines)


def _reject_block_marks(node: dict[str, object], path: tuple[str | int, ...]) -> None:
    marks = node.get("marks", [])
    if not isinstance(marks, list):
        raise AdfConversionError("ADF block marks must be an array", path=pointer(path))
    for index, mark_value in enumerate(marks):
        mark_path = (*path, "marks", index)
        if not isinstance(mark_value, dict):
            raise AdfConversionError(
                "ADF mark must be an object", path=pointer(mark_path)
            )
        mark_type = mark_value.get("type")
        if mark_type in FATAL_BLOCK_MARK_TYPES:
            raise AdfConversionError(
                f"ADF {mark_type!r} block marks are outside the Jira/GFM profile",
                path=pointer(mark_path),
            )
        raise AdfConversionError(
            f"ADF block mark {mark_type!r} is outside the Jira/GFM profile",
            path=pointer(mark_path),
        )


def _is_empty_gfm_paragraph(
    node: dict[str, object], state: _RenderState, path: tuple[str | int, ...]
) -> bool:
    """Render-policy check for the empty paragraph shape emitted by GFM."""

    if node.get("type") != "paragraph" or _content(node):
        return False
    _reject_block_marks(node, path)
    state.discard(_attrs(node), {"localId"}, (*path, "attrs"))
    return True


def _is_whitespace_only_list_paragraph(nodes: list[dict[str, object]]) -> bool:
    """Whether list parsing would treat the sole paragraph as blank content."""

    if len(nodes) != 1 or nodes[0].get("type") != "paragraph":
        return False
    content = _content(nodes[0])
    semantic_content = content[: trailing_hard_break_start(content)]
    return bool(semantic_content) and all(
        child.get("type") == "text"
        and not child.get("marks", [])
        and isinstance(child.get("text"), str)
        and str(child["text"]).isspace()
        for child in semantic_content
    )


def _is_empty_or_whitespace_only_quote_paragraph(node: dict[str, object]) -> bool:
    """Whether a quote paragraph has no visible portable GFM content."""

    if node.get("type") != "paragraph":
        return False
    return is_empty_or_whitespace_only_quote_content(_content(node))


def _is_canonical_empty_root_paragraph(node: dict[str, object]) -> bool:
    """Whether this is the sole root representation of empty visible Markdown."""

    return node == {"type": "paragraph"}


def _render_list(
    node: dict[str, object],
    state: _RenderState,
    path: tuple[str | int, ...],
    *,
    marker: str | None = None,
) -> str:
    node_type = node.get("type")
    attrs = _attrs(node)
    items = _content(node)
    order = attrs.get("order", 1)
    if node_type == "orderedList":
        if not isinstance(order, int) or order < 0:
            raise AdfConversionError(
                "ordered list order must be a non-negative integer",
                path=pointer((*path, "attrs", "order")),
            )
        if items and order + len(items) - 1 > 999_999_999:
            raise AdfConversionError(
                "ordered list markers must contain at most nine digits",
                path=pointer((*path, "attrs", "order")),
            )
        number = order
        delimiter = marker or "."
    else:
        number = 1
        bullet = marker or "-"
    state.discard(attrs, {"order", "localId"}, (*path, "attrs"), preserved={"order"})
    lines: list[str] = []
    for index, item in enumerate(items):
        item_path = (*path, "content", index)
        if item.get("type") != "listItem":
            raise AdfConversionError(
                "list contains a non-listItem node", path=pointer(item_path)
            )
        item_attrs = _attrs(item)
        state.discard(item_attrs, {"localId"}, (*item_path, "attrs"))
        item_content = _content(item)
        body = (
            ""
            if len(item_content) == 1
            and _is_empty_gfm_paragraph(
                item_content[0], state, (*item_path, "content", 0)
            )
            else _render_blocks(
                item_content,
                state,
                (*item_path, "content"),
                boundary_owner=(
                    "list item"
                    if _is_whitespace_only_list_paragraph(item_content)
                    else None
                ),
            )
        )
        item_marker = (
            f"{number + index}{delimiter} "
            if node_type == "orderedList"
            else f"{bullet} "
        )
        item_lines = body.split("\n")
        lines.append(item_marker.rstrip() if not body else item_marker + item_lines[0])
        indent = " " * len(item_marker)
        lines.extend(
            indent + line if line else indent.rstrip() for line in item_lines[1:]
        )
    return "\n".join(lines)


def _render_block(
    node: dict[str, object],
    state: _RenderState,
    path: tuple[str | int, ...],
    *,
    table_cell: bool,
    list_marker: str | None = None,
    boundary_owner: str | None = None,
    source_left_edge: bool = False,
    source_right_edge: bool = False,
) -> str:
    node_type = node.get("type")
    if node_type in MEDIA_CONTEXT_TYPES:
        _reject_media_marks(node, path)
    else:
        _reject_block_marks(node, path)
    if node_type == "paragraph":
        content = _content(node)
        if not content:
            raise AdfConversionError(
                "empty ADF paragraphs are outside the portable GFM profile",
                path=pointer(path),
            )
        attrs = _attrs(node)
        state.discard(attrs, {"localId"}, (*path, "attrs"))
        return _render_inline(
            content,
            state,
            (*path, "content"),
            table_cell=table_cell,
            boundary_owner=boundary_owner,
            source_left_edge=source_left_edge,
            source_right_edge=source_right_edge,
        )
    if node_type == "heading":
        content = _content(node)
        for index, child in enumerate(content[: trailing_hard_break_start(content)]):
            if child.get("type") == "hardBreak":
                raise AdfConversionError(
                    "nonterminal heading hard breaks cannot round-trip in Markdown",
                    path=pointer((*path, "content", index)),
                )
        attrs = _attrs(node)
        state.discard(
            attrs, {"level", "localId"}, (*path, "attrs"), preserved={"level"}
        )
        level = attrs.get("level")
        if not isinstance(level, int) or not 1 <= level <= 6:
            raise AdfConversionError("heading level is invalid", path=pointer(path))
        inline = _render_inline(
            content, state, (*path, "content"), table_cell=table_cell
        )
        return "#" * level + " " + _source_encode_heading_closing_hashes(inline)
    if node_type == "blockquote":
        attrs = _attrs(node)
        state.discard(attrs, {"localId"}, (*path, "attrs"))
        content = _content(node)
        if not content:
            raise AdfConversionError(
                "empty ADF block quotes are outside the portable GFM profile",
                path=pointer(path),
            )
        body = _render_blocks(
            content,
            state,
            (*path, "content"),
            table_cell=table_cell,
            boundary_owner="block quote",
        )
        lines = body.split("\n")
        terminal_newline = len(lines) > 1 and not lines[-1]
        if terminal_newline:
            lines.pop()
        rendered = "\n".join("> " + line if line else ">" for line in lines)
        return rendered + ("\n" if terminal_newline else "")
    if node_type in {"bulletList", "orderedList"}:
        return _render_list(node, state, path, marker=list_marker)
    if node_type == "codeBlock":
        attrs = _attrs(node)
        state.discard(
            attrs,
            {"language", "uniqueId", "localId", "wrap", "hideLineNumbers"},
            (*path, "attrs"),
            preserved={"language"},
        )
        language = attrs.get("language")
        if language is not None and not isinstance(language, str):
            raise AdfConversionError(
                "code block language is invalid", path=pointer(path)
            )
        if isinstance(language, str) and not _SAFE_CODE_LANGUAGE.fullmatch(language):
            state.warn(
                "adf.code_language_discarded",
                "code block language is not safe as a Markdown fence info string",
                (*path, "attrs", "language"),
            )
            language = None
        code = "".join(
            _normalize_nul_text(
                str(child.get("text", "")),
                state,
                (*path, "content", index, "text"),
            )
            for index, child in enumerate(_content(node))
        )
        normalized_code = _normalize_code_block_text(code, state, (*path, "content"))
        fence = _block_fence(normalized_code)
        return f"{fence}{language or ''}\n{normalized_code}{fence}"
    if node_type == "rule":
        attrs = _attrs(node)
        state.discard(attrs, {"localId"}, (*path, "attrs"))
        return "---"
    if node_type == "table":
        return _render_table(node, state, path)
    if node_type in {"expand", "nestedExpand"}:
        attrs = _attrs(node)
        state.warn(
            "adf.expand_degraded",
            "ADF expand container semantics are flattened in portable GFM",
            path,
        )
        state.discard(
            attrs, {"title", "localId"}, (*path, "attrs"), preserved={"title"}
        )
        title = attrs.get("title")
        if isinstance(title, str):
            title = _normalize_nul_text(title, state, (*path, "attrs", "title"))
        prefix = (
            f"**{_emit_literal(title, _LiteralContext(table_cell, False))}**"
            if isinstance(title, str) and title
            else ""
        )
        body = _render_blocks(
            _content(node), state, (*path, "content"), table_cell=table_cell
        )
        return "\n\n".join(part for part in (prefix, body) if part)
    if node_type == "panel":
        attrs = _attrs(node)
        state.warn(
            "adf.panel_degraded",
            "ADF panel presentation is flattened in portable GFM",
            path,
        )
        state.discard(
            attrs,
            {
                "panelType",
                "panelIcon",
                "panelIconId",
                "panelIconText",
                "panelColor",
                "localId",
            },
            (*path, "attrs"),
        )
        return _render_blocks(
            _content(node), state, (*path, "content"), table_cell=table_cell
        )
    if node_type == "mediaSingle":
        media = _content(node)
        for index, child in enumerate(media):
            _reject_media_marks(child, (*path, "content", index))
        attrs = _attrs(node)
        state.warn(
            "adf.media_single_degraded",
            "ADF media layout is flattened in portable GFM",
            path,
        )
        state.discard(
            attrs, {"layout", "width", "widthType", "localId"}, (*path, "attrs")
        )
        return "\n".join(
            _render_media(child, state, (*path, "content", index))
            for index, child in enumerate(media)
        )
    if node_type == "mediaGroup":
        media = _content(node)
        for index, child in enumerate(media):
            _reject_media_marks(child, (*path, "content", index))
        state.warn(
            "adf.media_group_degraded",
            "ADF media grouping is flattened in portable GFM",
            path,
        )
        return "\n".join(
            _render_media(child, state, (*path, "content", index))
            for index, child in enumerate(media)
        )
    if node_type == "media":
        return _render_media(node, state, path)
    raise AdfConversionError(
        f"ADF node {node_type!r} is outside the Jira/GFM profile", path=pointer(path)
    )


def _render_blocks(
    nodes: list[dict[str, object]],
    state: _RenderState,
    path: tuple[str | int, ...],
    *,
    table_cell: bool = False,
    boundary_owner: str | None = None,
) -> str:
    rendered: list[str] = []
    previous_list: tuple[str, str] | None = None
    markers = {"bulletList": ("-", "*"), "orderedList": (".", ")")}
    for index, node in enumerate(nodes):
        node_type = node.get("type")
        list_marker: str | None = None
        if isinstance(node_type, str) and node_type in markers:
            first, alternate = markers[node_type]
            if previous_list is not None and previous_list[0] == node_type:
                list_marker = alternate if previous_list[1] == first else first
            else:
                list_marker = first
            previous_list = (node_type, list_marker)
        else:
            previous_list = None
        node_path = (*path, index)
        if (
            boundary_owner == "block quote"
            and _is_empty_or_whitespace_only_quote_paragraph(node)
        ):
            raise AdfConversionError(
                "empty ADF block quote paragraphs are outside the portable GFM profile",
                path=pointer(node_path),
            )
        block = _render_block(
            node,
            state,
            node_path,
            table_cell=table_cell,
            list_marker=list_marker,
            boundary_owner=boundary_owner,
            source_left_edge=boundary_owner is not None
            and (boundary_owner == "block quote" or index == 0),
            source_right_edge=boundary_owner is not None
            and (boundary_owner == "block quote" or index == len(nodes) - 1),
        )
        if boundary_owner == "block quote" and not block:
            raise AdfConversionError(
                "ADF block quote children must render visible portable GFM content",
                path=pointer(node_path),
            )
        rendered.append(block)
    return "\n\n".join(rendered)


def adf_to_markdown(
    document: AdfDocument, *, strict: bool = False
) -> ConversionResult[str]:
    """Render a validated focused Jira ADF document as canonical portable GFM."""

    validate_adf(document)
    if document.get("type") != "doc":  # Defensive: the schema already enforces this.
        raise AdfConversionError("ADF root must be a doc node")
    state = _RenderState()
    content = _content(cast(dict[str, object], document))
    output = (
        ""
        if len(content) == 1 and _is_canonical_empty_root_paragraph(content[0])
        else _render_blocks(content, state, ("content",))
    )
    diagnostics = tuple(state.diagnostics)
    if strict and diagnostics:
        raise LossyConversionError(diagnostics)
    return ConversionResult(output, diagnostics)
