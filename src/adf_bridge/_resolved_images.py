"""Validation and identity helpers for caller-resolved Jira images."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ._errors import AdfConversionError
from ._types import ResolvedJiraImage


def _validated_resolved_images(
    resolved_images: object,
) -> dict[str, ResolvedJiraImage]:
    """Validate the narrow, data-only managed-media resolution contract."""

    if isinstance(resolved_images, (str, bytes, bytearray)) or not isinstance(
        resolved_images, Sequence
    ):
        raise TypeError("resolved_images must be a non-string sequence")

    resolutions: dict[str, ResolvedJiraImage] = {}
    identities: set[tuple[str, str]] = set()
    for resolution in resolved_images:
        if not isinstance(resolution, ResolvedJiraImage):
            raise TypeError("resolved_images must contain ResolvedJiraImage values")
        if not isinstance(resolution.source_url, str):
            raise TypeError("resolved image source_url must be a string")
        if not resolution.source_url:
            raise AdfConversionError(
                "resolved image source_url must be a nonempty string"
            )
        if not isinstance(resolution.media_id, str):
            raise TypeError("resolved image media_id must be a string")
        if not resolution.media_id:
            raise AdfConversionError(
                "resolved image media_id must be a nonempty string"
            )
        if not isinstance(resolution.collection, str):
            raise TypeError("resolved image collection must be a string")
        if (resolution.width is None) != (resolution.height is None):
            raise AdfConversionError(
                "resolved image width and height must be supplied together"
            )
        if resolution.width is not None:
            for name, value in (
                ("width", resolution.width),
                ("height", resolution.height),
            ):
                if not isinstance(value, int) or isinstance(value, bool):
                    raise TypeError(f"resolved image {name} must be an integer")
                if value <= 0:
                    raise AdfConversionError(
                        f"resolved image {name} must be a positive integer"
                    )
        if resolution.source_url in resolutions:
            raise AdfConversionError("resolved_images contains a duplicate source_url")
        identity = (resolution.media_id, resolution.collection)
        if identity in identities:
            raise AdfConversionError(
                "resolved_images contains a duplicate Jira media identity"
            )
        resolutions[resolution.source_url] = resolution
        identities.add(identity)
    return resolutions


def _resolved_image_identities(
    resolutions: Iterable[ResolvedJiraImage],
) -> set[tuple[str, str]]:
    """Return the exact Jira file identities represented by resolutions."""

    return {(resolution.media_id, resolution.collection) for resolution in resolutions}
