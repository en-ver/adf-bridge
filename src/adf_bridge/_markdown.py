"""Markdown-to-ADF conversion using Mistune's AST renderer."""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from html.entities import html5
from typing import Any, TypeVar, cast

import mistune
from mistune._inline.links import (
    build_link_token,
    find_closing_bracket,
    label_contains_link,
    mark_no_image_before,
    mark_no_link_before,
)
from mistune.helpers import (
    _parse_link_href,
    _skip_ascii_whitespace,
    parse_link_label,
    parse_link_title,
    unescape_char,
)
from mistune.plugins.formatting import strikethrough
from mistune.plugins.table import table, table_in_list, table_in_quote
from mistune.plugins.task_lists import task_lists
from mistune.plugins.url import url
from mistune.util import unikey

from ._errors import AdfConversionError, LossyConversionError
from ._jira_profile import (
    BLOCKQUOTE_CHILD_TYPES,
    TABLE_CELL_BREAK,
    is_empty_or_whitespace_only_quote_content,
    validate_mention_id,
)
from ._resolved_images import _validated_resolved_images
from ._schema import validate_adf
from ._types import AdfDocument, ConversionResult, Diagnostic, ResolvedJiraImage

Token = dict[str, Any]
T = TypeVar("T")
# Preserve ordinary Markdown links while allowing adjacent canonical mention syntax.
_ACCOUNT_MENTION = r"\[~(?i:accountid):(?P<account_id>[^\s\\\]]+)\](?!\()"
_ENTITY_REFERENCE = re.compile(
    r"&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]*);"
)
_COMMONMARK_BLANK_WHITESPACE = frozenset(" \t\r\n")


def _is_commonmark_blank(markdown: str) -> bool:
    return all(character in _COMMONMARK_BLANK_WHITESPACE for character in markdown)


def _parse_account_mention(inline: Any, match: re.Match[str], state: Any) -> int:
    if state.in_link or state.in_image:
        inline.process_text(match.group(0), state)
    else:
        state.append_token(
            {
                "type": "mention",
                "attrs": {"id": validate_mention_id(match.group("account_id"))},
            }
        )
    return match.end()


def _account_mentions(md: mistune.Markdown) -> None:
    md.inline.register(
        "account_mention", _ACCOUNT_MENTION, _parse_account_mention, before="link"
    )


def _parse_opaque_destination_with_end(
    source: str, position: int
) -> tuple[dict[str, object] | None, int | None, int]:
    """Parse a direct link without Mistune's URL percent-normalization."""

    href, href_position, scan_end = _parse_link_href(source, position)
    if href is None:
        return None, None, scan_end
    assert href_position is not None
    title, title_position = parse_link_title(source, href_position, len(source))
    next_position = title_position or href_position
    next_position = _skip_ascii_whitespace(source, next_position)
    if next_position >= len(source) or source[next_position] != ")":
        return None, None, next_position
    attrs: dict[str, object] = {"url": html.unescape(unescape_char(href))}
    if title:
        attrs["title"] = title
    return attrs, next_position + 1, next_position + 1


def _parse_opaque_destination_link(
    inline: Any, match: re.Match[str], state: Any
) -> int | None:
    """Mistune's direct-link parser with only its destination boundary replaced."""

    position = match.end()
    marker = match.group(0)
    is_image = marker[0] == "!"
    if (
        is_image
        and inline.max_image_depth > 0
        and state.image_depth >= inline.max_image_depth
    ):
        state.append_token({"type": "text", "raw": marker + state.src[position:]})
        return len(state.src)
    if not is_image and state.in_link:
        state.append_token({"type": "text", "raw": marker})
        return position
    if not is_image and position <= state.no_link_before:
        state.append_token({"type": "text", "raw": marker})
        return position
    if is_image and position <= state.no_image_before:
        state.append_token({"type": "text", "raw": marker})
        return position

    text = None
    text_start = position
    text_end = position
    label, end_position = parse_link_label(state.src, position)
    if label is None:
        if position <= state.no_close_bracket_before:
            state.append_token({"type": "text", "raw": marker})
            return position
        close_position = find_closing_bracket(state, position)
        if close_position is None:
            if len(state.src) > state.no_close_bracket_before:
                state.no_close_bracket_before = len(state.src)
            return None
        text_start = position
        text_end = close_position
        end_position = close_position + 1

    assert end_position is not None
    if label is not None:
        text = label
        text_start = position
        text_end = end_position - 1

    body_end = end_position
    if label_contains_link(state, text_start, text_end):
        return None
    if end_position >= len(state.src) and label is None:
        mark_no_link_before(state, body_end)
        return None

    if not is_image:
        precedence_position = inline.precedence_scan(
            match,
            state,
            end_position,
            ["codespan", "prec_auto_link", "prec_inline_html"],
        )
        if precedence_position:
            return precedence_position

    if end_position < len(state.src):
        character = state.src[end_position]
        if character == "(":
            attrs, parsed_position, scan_end = _parse_opaque_destination_with_end(
                state.src, end_position + 1
            )
            if parsed_position:
                if text is None:
                    text = state.src[text_start:text_end]
                state.append_token(
                    build_link_token(inline, is_image, text, attrs, state)
                )
                return parsed_position
            if scan_end > body_end:
                if is_image:
                    mark_no_image_before(state, scan_end)
                else:
                    mark_no_link_before(state, scan_end)
        elif character == "[":
            label2, parsed_position = parse_link_label(state.src, end_position + 1)
            if parsed_position:
                end_position = parsed_position
                if label2:
                    label = label2

    if label is None:
        ref_links = state.env.get("ref_links")
        if not ref_links:
            mark_no_link_before(state, body_end)
            return None
        if text is None:
            text = state.src[text_start:text_end]
        label = text
    ref_links = state.env.get("ref_links")
    if not ref_links:
        mark_no_link_before(state, body_end)
        return None

    key = unikey(label)
    environment = ref_links.get(key)
    if environment:
        if text is None:
            text = state.src[text_start:text_end]
        attrs = {"url": environment["url"], "title": environment.get("title")}
        token = build_link_token(inline, is_image, text, attrs, state)
        token["ref"] = key
        token["label"] = label
        state.append_token(token)
        return end_position
    mark_no_link_before(state, body_end)
    return None


_PARSER = mistune.create_markdown(
    renderer="ast",
    plugins=[
        table,
        table_in_list,
        table_in_quote,
        strikethrough,
        task_lists,
        url,
        _account_mentions,
    ],
)
_PARSER.inline.register("link", None, _parse_opaque_destination_link)


@dataclass
class _Collector:
    resolutions: dict[str, ResolvedJiraImage] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    used_resolutions: set[str] = field(default_factory=set)

    def warn(self, code: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(code, "warning", message))


def _validate_markdown_mention_ids(markdown: str) -> None:
    """Validate actual mention tokens before normalizing ordinary Markdown text."""

    if "\x00" in markdown:
        _PARSER.parse(markdown)


def _normalize_markdown_nuls(markdown: str, collector: _Collector) -> str:
    """Apply CommonMark's required NUL replacement once at the input boundary."""

    if "\x00" not in markdown:
        return markdown
    collector.warn(
        "markdown.nul_normalized",
        "Markdown U+0000 is normalized to U+FFFD by CommonMark",
    )
    return markdown.replace("\x00", "\ufffd")


def _text(text: str, marks: list[dict[str, object]]) -> dict[str, object] | None:
    if not text:
        return None
    node: dict[str, object] = {"type": "text", "text": text}
    if marks:
        node["marks"] = deepcopy(marks)
    return node


def _append_inline(
    content: list[dict[str, object]], node: dict[str, object] | None
) -> None:
    if node is None:
        return
    if (
        node.get("type") == "text"
        and content
        and content[-1].get("type") == "text"
        and content[-1].get("marks", []) == node.get("marks", [])
    ):
        content[-1]["text"] = str(content[-1]["text"]) + str(node["text"])
        return
    content.append(node)


def _decode_mention_id(value: object) -> str:
    if not isinstance(value, str):
        return validate_mention_id(value)
    return validate_mention_id(_decode_entities(value))


def _decode_entities(text: str) -> str:
    """Decode only complete CommonMark entity references."""

    def replace(match: re.Match[str]) -> str:
        entity = match.group()
        if entity.startswith("&#") or entity[1:] in html5:
            return html.unescape(entity)
        return entity

    return _ENTITY_REFERENCE.sub(replace, text)


def _plain_inline(tokens: list[Token]) -> str:
    parts: list[str] = []
    for token in tokens:
        token_type = token["type"]
        if token_type == "text":
            parts.append(_decode_entities(str(token.get("raw", ""))))
        elif token_type in {"softbreak", "linebreak"}:
            parts.append(" ")
        elif token_type in {"codespan", "inline_html"}:
            parts.append(str(token.get("raw", "")))
        elif "children" in token:
            parts.append(_plain_inline(cast(list[Token], token["children"])))
        elif token_type == "mention":
            parts.append(f"[~accountId:{token['attrs']['id']}]")
    return "".join(parts)


def _inline(
    tokens: list[Token],
    collector: _Collector,
    marks: list[dict[str, object]] | None = None,
    *,
    table_cell: bool = False,
    allow_block_media: bool = True,
) -> list[dict[str, object]]:
    active_marks = [] if marks is None else marks
    content: list[dict[str, object]] = []
    for token in tokens:
        token_type = token["type"]
        if token_type == "text":
            _append_inline(
                content,
                _text(_decode_entities(str(token.get("raw", ""))), active_marks),
            )
        elif token_type == "softbreak":
            _append_inline(content, _text(" ", active_marks))
        elif token_type == "linebreak":
            _append_inline(content, {"type": "hardBreak"})
        elif token_type == "codespan":
            raw = str(token.get("raw", ""))
            if table_cell:
                raw = raw.replace(r"\|", "|")
            _append_inline(content, _text(raw, [*active_marks, {"type": "code"}]))
        elif token_type in {"emphasis", "strong", "strikethrough"}:
            mark_type = {
                "emphasis": "em",
                "strong": "strong",
                "strikethrough": "strike",
            }[token_type]
            content.extend(
                _inline(
                    cast(list[Token], token.get("children", [])),
                    collector,
                    [*active_marks, {"type": mark_type}],
                    table_cell=table_cell,
                    allow_block_media=allow_block_media,
                )
            )
        elif token_type == "link":
            attrs = cast(dict[str, object], token.get("attrs", {}))
            href = attrs.get("url")
            if not isinstance(href, str) or not href:
                raise AdfConversionError("Markdown link has no usable URL")
            link_attrs: dict[str, object] = {"href": href}
            title = attrs.get("title")
            if isinstance(title, str):
                link_attrs["title"] = _decode_entities(title)
            linked_content = _inline(
                cast(list[Token], token.get("children", [])),
                collector,
                [*active_marks, {"type": "link", "attrs": link_attrs}],
                table_cell=table_cell,
                allow_block_media=allow_block_media,
            )
            if not linked_content:
                raise AdfConversionError("empty Markdown links are outside the profile")
            content.extend(linked_content)
        elif token_type == "image":
            if not allow_block_media:
                raise AdfConversionError(
                    "images are outside this Markdown block context"
                )
            if active_marks:
                raise AdfConversionError(
                    "formatted inline images are outside the profile"
                )
            attrs = cast(dict[str, object], token.get("attrs", {}))
            image_url = attrs.get("url")
            if not isinstance(image_url, str) or not image_url:
                raise AdfConversionError("Markdown image has no usable URL")
            collector.image_urls.append(image_url)
            resolution = collector.resolutions.get(image_url)
            if resolution is None:
                media_attrs: dict[str, object] = {
                    "type": "external",
                    "url": image_url,
                }
            else:
                collector.used_resolutions.add(image_url)
                media_attrs = {
                    "type": "file",
                    "id": resolution.media_id,
                    "collection": resolution.collection,
                }
            if isinstance(attrs.get("title"), str):
                collector.warn(
                    "markdown.image_title_discarded",
                    "Markdown image titles cannot be represented in Jira ADF media",
                )
            alt = _plain_inline(cast(list[Token], token.get("children", [])))
            if alt:
                media_attrs["alt"] = alt
            content.append(
                {
                    "type": "_block_media",
                    "value": {
                        "type": "mediaSingle",
                        "attrs": {"layout": "center"},
                        "content": [{"type": "media", "attrs": media_attrs}],
                    },
                }
            )
        elif token_type == "mention":
            if active_marks:
                collector.warn(
                    "markdown.mention_marks_discarded",
                    "Formatting around a Jira mention cannot be represented in ADF "
                    "and was discarded",
                )
            attrs = cast(dict[str, object], token.get("attrs", {}))
            content.append(
                {
                    "type": "mention",
                    "attrs": {"id": _decode_mention_id(attrs.get("id"))},
                }
            )
        elif (
            token_type == "inline_html"
            and table_cell
            and token.get("raw") == TABLE_CELL_BREAK
        ):
            _append_inline(content, {"type": "hardBreak"})
        elif token_type == "inline_html":
            collector.warn(
                "markdown.raw_html", "raw HTML is preserved as literal text in ADF"
            )
            _append_inline(content, _text(str(token.get("raw", "")), active_marks))
        else:
            raise AdfConversionError(f"unsupported Markdown token {token_type!r}")
    return content


def _paragraph_blocks(
    tokens: list[Token], collector: _Collector, *, table_cell: bool = False
) -> list[dict[str, object]]:
    inline = _inline(tokens, collector, table_cell=table_cell)
    blocks: list[dict[str, object]] = []
    current: list[dict[str, object]] = []
    has_surrounding_content = any(node["type"] != "_block_media" for node in inline)
    for node in inline:
        if node["type"] == "_block_media":
            if current:
                blocks.append({"type": "paragraph", "content": current})
                current = []
            blocks.append(cast(dict[str, object], node["value"]))
        else:
            current.append(node)
    if current:
        blocks.append({"type": "paragraph", "content": current})
    if not blocks:
        blocks.append({"type": "paragraph"})
    if has_surrounding_content and any(
        node["type"] == "_block_media" for node in inline
    ):
        collector.warn(
            "markdown.image_promoted", "inline image was promoted to a block media node"
        )
    return blocks


def _code_block(token: Token, collector: _Collector) -> dict[str, object]:
    attrs = cast(dict[str, object], token.get("attrs", {}))
    info = attrs.get("info")
    node: dict[str, object] = {"type": "codeBlock"}
    if isinstance(info, str) and info.strip():
        language, *extra = info.split(maxsplit=1)
        node["attrs"] = {"language": language}
        if extra:
            collector.warn(
                "markdown.code_info_discarded",
                "extra fenced-code information cannot be represented in ADF",
            )
    raw = str(token.get("raw", ""))
    if raw:
        node["content"] = [{"type": "text", "text": raw}]
    return node


def _list(token: Token, collector: _Collector) -> dict[str, object]:
    attrs = cast(dict[str, object], token.get("attrs", {}))
    ordered = bool(attrs.get("ordered"))
    content: list[dict[str, object]] = []
    for item in cast(list[Token], token.get("children", [])):
        item_type = item["type"]
        if item_type not in {"list_item", "task_list_item"}:
            raise AdfConversionError(f"unsupported list token {item_type!r}")
        blocks: list[dict[str, object]] = _blocks(
            cast(list[Token], item.get("children", [])), collector
        )
        if not blocks:
            blocks = [{"type": "paragraph"}]
        permitted = {
            "paragraph",
            "bulletList",
            "orderedList",
            "codeBlock",
            "mediaSingle",
        }
        if any(block["type"] not in permitted for block in blocks):
            raise AdfConversionError(
                "this Markdown block is not supported inside a list"
            )
        if item_type == "task_list_item":
            checked = bool(
                cast(dict[str, object], item.get("attrs", {})).get("checked")
            )
            prefix = "[x] " if checked else "[ ] "
            first = blocks[0]
            if first["type"] != "paragraph":
                blocks.insert(
                    0,
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": prefix}],
                    },
                )
            else:
                first_content = first.get("content")
                if not isinstance(first_content, list):
                    first_content = []
                    first["content"] = first_content
                first_content.insert(0, {"type": "text", "text": prefix})
            collector.warn(
                "markdown.task_list_degraded",
                "task list state is visible text rather than Jira task nodes",
            )
        content.append({"type": "listItem", "content": blocks})
    if not content:
        raise AdfConversionError("empty Markdown lists are outside the profile")
    if ordered:
        node: dict[str, object] = {"type": "orderedList", "content": content}
        start = attrs.get("start", 1)
        if isinstance(start, int) and start != 1:
            node["attrs"] = {"order": start}
        return node
    return {"type": "bulletList", "content": content}


def _table(token: Token, collector: _Collector) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for section in cast(list[Token], token.get("children", [])):
        section_type = section["type"]
        if section_type not in {"table_head", "table_body"}:
            raise AdfConversionError(f"unsupported table token {section_type!r}")
        section_rows = (
            [{"type": "table_row", "children": section.get("children", [])}]
            if section_type == "table_head"
            else cast(list[Token], section.get("children", []))
        )
        for row in section_rows:
            cells: list[dict[str, object]] = []
            for cell in cast(list[Token], row.get("children", [])):
                attrs = cast(dict[str, object], cell.get("attrs", {}))
                if attrs.get("align"):
                    collector.warn(
                        "markdown.table_alignment_discarded",
                        "Markdown table alignment cannot be represented in Jira ADF",
                    )
                cell_type = (
                    "tableHeader" if section_type == "table_head" else "tableCell"
                )
                paragraph = _paragraph_blocks(
                    cast(list[Token], cell.get("children", [])),
                    collector,
                    table_cell=True,
                )
                if any(block["type"] != "paragraph" for block in paragraph):
                    raise AdfConversionError(
                        "images are not supported inside Markdown table cells"
                    )
                cells.append({"type": cell_type, "content": paragraph})
            rows.append({"type": "tableRow", "content": cells})
    if not rows:
        raise AdfConversionError("empty Markdown tables are outside the profile")
    return {"type": "table", "content": rows}


def _blocks(tokens: list[Token], collector: _Collector) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for token in tokens:
        token_type = token["type"]
        if token_type in {"paragraph", "block_text"}:
            blocks.extend(
                _paragraph_blocks(
                    cast(list[Token], token.get("children", [])), collector
                )
            )
        elif token_type == "heading":
            attrs = cast(dict[str, object], token.get("attrs", {}))
            level = attrs.get("level")
            if not isinstance(level, int) or not 1 <= level <= 6:
                raise AdfConversionError("Markdown heading has an invalid level")
            content = _inline(
                cast(list[Token], token.get("children", [])),
                collector,
                allow_block_media=False,
            )
            blocks.append(
                {"type": "heading", "attrs": {"level": level}, "content": content}
            )
        elif token_type == "block_code":
            blocks.append(_code_block(token, collector))
        elif token_type == "block_quote":
            content = _blocks(cast(list[Token], token.get("children", [])), collector)
            if not content or any(
                block["type"] == "paragraph"
                and (
                    not (paragraph_content := block.get("content"))
                    or not isinstance(paragraph_content, list)
                    or is_empty_or_whitespace_only_quote_content(
                        cast(list[dict[str, object]], paragraph_content)
                    )
                )
                for block in content
            ):
                raise AdfConversionError(
                    "empty Markdown block quotes are outside the profile"
                )
            if any(block["type"] not in BLOCKQUOTE_CHILD_TYPES for block in content):
                raise AdfConversionError(
                    "this Markdown block is not supported inside a block quote"
                )
            blocks.append({"type": "blockquote", "content": content})
        elif token_type == "list":
            blocks.append(_list(token, collector))
        elif token_type == "thematic_break":
            blocks.append({"type": "rule"})
        elif token_type == "table":
            blocks.append(_table(token, collector))
        elif token_type == "block_html":
            collector.warn(
                "markdown.raw_html", "raw HTML is preserved as literal text in ADF"
            )
            raw = str(token.get("raw", ""))
            blocks.append(
                {"type": "paragraph", "content": [{"type": "text", "text": raw}]}
            )
        elif token_type == "blank_line":
            continue
        else:
            raise AdfConversionError(f"unsupported Markdown token {token_type!r}")
    return blocks


def _convert_markdown(
    markdown: str, resolutions: dict[str, ResolvedJiraImage]
) -> tuple[AdfDocument, _Collector]:
    """Parse and convert Markdown once for both discovery and construction."""

    if not isinstance(markdown, str):
        raise TypeError("markdown must be a string")
    collector = _Collector(resolutions=resolutions)
    _validate_markdown_mention_ids(markdown)
    markdown = _normalize_markdown_nuls(markdown, collector)
    if _is_commonmark_blank(markdown):
        content: list[dict[str, object]] = [{"type": "paragraph"}]
    else:
        tokens, state = _PARSER.parse(markdown)
        content = _blocks(cast(list[Token], tokens), collector)
        if not content:
            if state.env.get("ref_links"):
                collector.warn(
                    "markdown.reference_definitions_discarded",
                    "Markdown reference definitions have no ADF representation "
                    "and were discarded",
                )
                content = [{"type": "paragraph"}]
            else:
                content = cast(
                    list[dict[str, object]],
                    [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": markdown}],
                        }
                    ],
                )
    document: AdfDocument = {"type": "doc", "version": 1, "content": content}
    validate_adf(document)
    return document, collector


def _conversion_result(
    value: T, collector: _Collector, strict: bool
) -> ConversionResult[T]:
    diagnostics = tuple(collector.diagnostics)
    if strict and diagnostics:
        raise LossyConversionError(diagnostics)
    return ConversionResult(value, diagnostics)


def markdown_image_urls(
    markdown: str, *, strict: bool = False
) -> ConversionResult[tuple[str, ...]]:
    """Return supported Markdown image destinations in source order."""

    _, collector = _convert_markdown(markdown, {})
    return _conversion_result(tuple(collector.image_urls), collector, strict)


def markdown_to_adf(
    markdown: str,
    *,
    strict: bool = False,
    resolved_images: Sequence[ResolvedJiraImage] = (),
) -> ConversionResult[AdfDocument]:
    """Convert portable GFM Markdown into the focused Jira ADF profile."""

    resolutions = _validated_resolved_images(resolved_images)
    document, collector = _convert_markdown(markdown, resolutions)
    unused = set(resolutions).difference(collector.used_resolutions)
    if unused:
        raise AdfConversionError("resolved_images contains an unused source_url")
    return _conversion_result(document, collector, strict)
