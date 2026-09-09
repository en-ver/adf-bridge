"""Structural verification for Jira-persisted managed media."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import NoReturn, cast

from ._errors import AdfValidationError, JiraMediaVerificationError
from ._jira_profile import pointer
from ._resolved_images import _resolved_image_identities, _validated_resolved_images
from ._schema import validate_adf
from ._types import AdfDocument, ResolvedJiraImage


@dataclass(frozen=True, slots=True)
class _ManagedMedia:
    container_path: tuple[str | int, ...]
    media_path: tuple[str | int, ...]
    identity: tuple[str, str]
    layout: str
    parent_width: int | float | None
    parent_width_type: str | None
    child_width: int | None
    child_height: int | None
    alt: str | None


def _fail(message: str, path: tuple[str | int, ...]) -> NoReturn:
    raise JiraMediaVerificationError(message, path=pointer(path))


def _validate_document(document: AdfDocument, label: str) -> None:
    try:
        validate_adf(document)
    except AdfValidationError as exc:
        path = exc.path
    else:
        return
    raise JiraMediaVerificationError(f"{label} ADF fails schema validation", path=path)


def _iter_nodes(
    value: object, path: tuple[str | int, ...] = ()
) -> Iterator[tuple[dict[str, object], tuple[str | int, ...]]]:
    if not isinstance(value, dict):
        return
    node = cast(dict[str, object], value)
    yield node, path
    content = node.get("content")
    if isinstance(content, list):
        for index, child in enumerate(content):
            if isinstance(child, dict):
                yield from _iter_nodes(child, (*path, "content", index))


def _value_at_path(document: AdfDocument, path: tuple[str | int, ...]) -> object | None:
    value: object = document
    for part in path:
        if isinstance(part, str) and isinstance(value, dict):
            if part not in value:
                return None
            value = value[part]
        elif isinstance(part, int) and isinstance(value, list):
            if part >= len(value):
                return None
            value = value[part]
        else:
            return None
    return value


def _media_identity(
    node: dict[str, object], identities: set[tuple[str, str]]
) -> tuple[str, str] | None:
    if node.get("type") != "media":
        return None
    attrs = node.get("attrs")
    if not isinstance(attrs, dict) or attrs.get("type") != "file":
        return None
    media_id = attrs.get("id")
    collection = attrs.get("collection")
    if not isinstance(media_id, str) or not isinstance(collection, str):
        return None
    identity = (media_id, collection)
    return identity if identity in identities else None


def _attrs(node: dict[str, object], path: tuple[str | int, ...]) -> dict[str, object]:
    attrs = node.get("attrs")
    if not isinstance(attrs, dict):
        _fail("managed media node attrs must be an object", (*path, "attrs"))
    return cast(dict[str, object], attrs)


def _reject_unknown_keys(
    value: dict[str, object], allowed: set[str], path: tuple[str | int, ...]
) -> None:
    for name in value:
        if name not in allowed:
            _fail(
                "managed media contains an unsupported structural member", (*path, name)
            )


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _parent_sizing(
    attrs: dict[str, object], path: tuple[str | int, ...]
) -> tuple[int | float | None, str | None]:
    has_width = "width" in attrs
    has_width_type = "widthType" in attrs
    if has_width != has_width_type:
        _fail("managed media sizing requires width and widthType", path)
    if not has_width:
        return None, None
    width = attrs["width"]
    width_type = attrs["widthType"]
    if not _number(width):
        _fail("managed media width must be a number", (*path, "width"))
    if not isinstance(width_type, str):
        _fail("managed media widthType must be a string", (*path, "widthType"))
    return cast(int | float, width), width_type


def _child_dimensions(
    attrs: dict[str, object], path: tuple[str | int, ...]
) -> tuple[int | None, int | None]:
    has_width = "width" in attrs
    has_height = "height" in attrs
    if has_width != has_height:
        _fail("managed media dimensions require width and height", path)
    if not has_width:
        return None, None
    width = attrs["width"]
    height = attrs["height"]
    if not _positive_int(width):
        _fail("managed media width must be a positive integer", (*path, "width"))
    if not _positive_int(height):
        _fail("managed media height must be a positive integer", (*path, "height"))
    return cast(int, width), cast(int, height)


def _alt(attrs: dict[str, object], path: tuple[str | int, ...]) -> str | None:
    value = attrs.get("alt")
    if value is None:
        return None
    if not isinstance(value, str):
        _fail("managed media alt must be a string", (*path, "alt"))
    return value


def _verify_managed_media(
    value: object,
    path: tuple[str | int, ...],
    identity: tuple[str, str],
    *,
    persisted: bool,
    expected: _ManagedMedia | None = None,
) -> _ManagedMedia:
    if not isinstance(value, dict):
        _fail("managed media is no longer a mediaSingle node", path)
    node = cast(dict[str, object], value)
    if node.get("type") != "mediaSingle":
        _fail("managed media is no longer a mediaSingle node", (*path, "type"))
    _reject_unknown_keys(node, {"type", "attrs", "content"}, path)

    container_attrs = _attrs(node, path)
    allowed_container_attrs = {"layout", "width", "widthType"}
    if persisted:
        allowed_container_attrs.add("localId")
    _reject_unknown_keys(container_attrs, allowed_container_attrs, (*path, "attrs"))
    layout = container_attrs.get("layout")
    if not isinstance(layout, str):
        _fail("managed mediaSingle has no layout", (*path, "attrs", "layout"))
    parent_width, parent_width_type = _parent_sizing(container_attrs, (*path, "attrs"))
    if expected is not None:
        if layout != expected.layout:
            _fail("persisted managed media layout changed", (*path, "attrs", "layout"))
        if expected.parent_width is not None:
            if parent_width is None:
                _fail(
                    "persisted managed media width is missing",
                    (*path, "attrs", "width"),
                )
            if parent_width != expected.parent_width or type(parent_width) is not type(
                expected.parent_width
            ):
                _fail(
                    "persisted managed media width changed", (*path, "attrs", "width")
                )
            if parent_width_type != expected.parent_width_type:
                _fail(
                    "persisted managed media widthType changed",
                    (*path, "attrs", "widthType"),
                )

    content = node.get("content")
    if not isinstance(content, list) or len(content) != 1:
        _fail(
            "managed mediaSingle must contain exactly one media child",
            (*path, "content"),
        )
    media = content[0]
    media_path = (*path, "content", 0)
    if not isinstance(media, dict) or media.get("type") != "media":
        _fail("managed mediaSingle child is no longer media", (*media_path, "type"))
    media_node = cast(dict[str, object], media)
    _reject_unknown_keys(media_node, {"type", "attrs"}, media_path)
    media_attrs = _attrs(media_node, media_path)
    allowed_media_attrs = {"type", "id", "collection", "alt", "width", "height"}
    if persisted:
        allowed_media_attrs.update({"localId", "occurrenceKey"})
    _reject_unknown_keys(media_attrs, allowed_media_attrs, (*media_path, "attrs"))
    if media_attrs.get("type") != "file":
        _fail("managed media is no longer file media", (*media_path, "attrs", "type"))
    if media_attrs.get("id") != identity[0]:
        _fail("persisted managed media ID changed", (*media_path, "attrs", "id"))
    if media_attrs.get("collection") != identity[1]:
        _fail(
            "persisted managed media collection changed",
            (*media_path, "attrs", "collection"),
        )
    child_width, child_height = _child_dimensions(media_attrs, (*media_path, "attrs"))
    if expected is not None and expected.child_width is not None:
        if child_width is None:
            _fail(
                "persisted managed media dimensions are missing",
                (*media_path, "attrs", "width"),
            )
        if child_width != expected.child_width or child_height != expected.child_height:
            _fail(
                "persisted managed media dimensions changed",
                (*media_path, "attrs"),
            )
    alt = _alt(media_attrs, (*media_path, "attrs"))
    if expected is not None:
        if expected.alt not in (None, ""):
            if alt != expected.alt:
                _fail(
                    "persisted managed media alt changed", (*media_path, "attrs", "alt")
                )
        elif alt not in (None, ""):
            _fail("persisted managed media alt changed", (*media_path, "attrs", "alt"))
    return _ManagedMedia(
        path,
        media_path,
        identity,
        layout,
        parent_width,
        parent_width_type,
        child_width,
        child_height,
        alt,
    )


def _submitted_media(
    document: AdfDocument, identities: set[tuple[str, str]]
) -> list[_ManagedMedia]:
    managed: list[_ManagedMedia] = []
    for node, media_path in _iter_nodes(document):
        identity = _media_identity(node, identities)
        if identity is None:
            continue
        if len(media_path) < 2 or media_path[-2] != "content":
            _fail("managed media is not inside a mediaSingle node", media_path)
        container_path = media_path[:-2]
        container = _value_at_path(document, container_path)
        managed.append(
            _verify_managed_media(container, container_path, identity, persisted=False)
        )
    return managed


def _verify_submitted_resolution(
    media: _ManagedMedia, resolution: ResolvedJiraImage
) -> None:
    attrs_path = (*media.container_path, "attrs")
    child_attrs_path = (*media.media_path, "attrs")
    if media.layout != "center":
        _fail("submitted managed media layout must be center", (*attrs_path, "layout"))
    if resolution.width is None:
        if media.parent_width is not None:
            _fail("legacy managed media must be widthless", (*attrs_path, "width"))
        if media.child_width is not None:
            _fail(
                "legacy managed media must have no dimensions",
                (*child_attrs_path, "width"),
            )
        return

    assert resolution.height is not None
    if media.parent_width != 100:
        _fail("dimensioned managed media width must be 100", (*attrs_path, "width"))
    if media.parent_width_type != "percentage":
        _fail(
            "dimensioned managed media widthType must be percentage",
            (*attrs_path, "widthType"),
        )
    if media.child_width is None:
        _fail(
            "dimensioned managed media dimensions are missing",
            (*child_attrs_path, "width"),
        )
    if media.child_width != resolution.width or media.child_height != resolution.height:
        _fail(
            "submitted managed media dimensions differ from its resolution",
            child_attrs_path,
        )


def verify_jira_media_readback(
    submitted: AdfDocument,
    persisted: AdfDocument,
    *,
    resolved_images: Sequence[ResolvedJiraImage],
) -> None:
    """Verify Jira retained caller-resolved media at the submitted JSON paths."""

    resolutions = _validated_resolved_images(resolved_images)
    identities = _resolved_image_identities(resolutions.values())
    resolutions_by_identity = {
        (resolution.media_id, resolution.collection): resolution
        for resolution in resolutions.values()
    }
    _validate_document(submitted, "submitted")
    _validate_document(persisted, "persisted")

    submitted_media = _submitted_media(submitted, identities)
    submitted_identities = {media.identity for media in submitted_media}
    if identities.difference(submitted_identities):
        _fail("submitted ADF does not contain every resolved Jira media identity", ())
    for media in submitted_media:
        _verify_submitted_resolution(media, resolutions_by_identity[media.identity])

    expected_media_paths = {media.media_path for media in submitted_media}
    for expected in submitted_media:
        persisted_container = _value_at_path(persisted, expected.container_path)
        _verify_managed_media(
            persisted_container,
            expected.container_path,
            expected.identity,
            persisted=True,
            expected=expected,
        )

    for node, media_path in _iter_nodes(persisted):
        if (
            _media_identity(node, identities) is not None
            and media_path not in expected_media_paths
        ):
            _fail("persisted ADF contains additional resolved Jira media", media_path)
