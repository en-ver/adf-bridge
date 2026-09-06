from collections.abc import Iterable
from copy import deepcopy
from typing import get_type_hints

import pytest

from adf_bridge import (
    AdfConversionError,
    Diagnostic,
    JiraMediaVerificationError,
    LossyConversionError,
    ResolvedJiraImage,
    markdown_image_urls,
    markdown_to_adf,
    verify_jira_media_readback,
)


def test_markdown_image_urls_uses_the_conversion_profile() -> None:
    markdown = """![direct](https://images.test/direct.png)
![reference][image]
![repeat](https://images.test/direct.png)

[image]: https://images.test/reference.png

[ordinary link](https://images.test/link.png)
`![code](https://images.test/code.png)`
<img src="https://images.test/html.png">
\\![escaped](https://images.test/escaped.png)
"""

    discovered = markdown_image_urls(markdown)
    converted = markdown_to_adf(markdown)

    assert discovered.value == (
        "https://images.test/direct.png",
        "https://images.test/reference.png",
        "https://images.test/direct.png",
    )
    assert discovered.diagnostics == converted.diagnostics
    with pytest.raises(LossyConversionError) as raised:
        markdown_image_urls('![alt](https://images.test/a.png "title")', strict=True)
    assert (
        raised.value.diagnostics
        == markdown_to_adf('![alt](https://images.test/a.png "title")').diagnostics
    )
    with pytest.raises(AdfConversionError):
        markdown_image_urls("# ![alt](https://images.test/a.png)")


def test_resolved_images_are_exact_managed_file_media_per_occurrence() -> None:
    source_url = "https://jira.test/rest/api/3/attachment/content/42"
    result = markdown_to_adf(
        f"![first]({source_url})\n\n![second]({source_url})\n\n![outside](https://x.test/a)",
        resolved_images=(ResolvedJiraImage(source_url, "media-42", ""),),
    )

    first, second, external = result.value["content"]
    assert first == {
        "type": "mediaSingle",
        "attrs": {"layout": "center"},
        "content": [
            {
                "type": "media",
                "attrs": {
                    "type": "file",
                    "id": "media-42",
                    "collection": "",
                    "alt": "first",
                },
            }
        ],
    }
    assert second["content"][0]["attrs"] == {
        "type": "file",
        "id": "media-42",
        "collection": "",
        "alt": "second",
    }
    assert external["content"][0]["attrs"] == {
        "type": "external",
        "url": "https://x.test/a",
        "alt": "outside",
    }
    assert (
        result.diagnostics
        == markdown_to_adf(
            f"![first]({source_url})\n\n![second]({source_url})\n\n![outside](https://x.test/a)"
        ).diagnostics
    )


def test_resolved_image_contract_rejects_invalid_duplicate_and_unused_mappings() -> (
    None
):
    source_url = "https://images.test/a.png"
    resolution = ResolvedJiraImage(source_url, "media-a", "")

    for value in ("not a sequence", (object(),)):
        with pytest.raises(TypeError):
            markdown_to_adf("plain", resolved_images=value)  # type: ignore[arg-type]
    for value in (
        ResolvedJiraImage("", "media-a", ""),
        ResolvedJiraImage(source_url, "", ""),
    ):
        with pytest.raises(AdfConversionError):
            markdown_to_adf("plain", resolved_images=(value,))
    for value in (
        ResolvedJiraImage(None, "media-a", ""),  # type: ignore[arg-type]
        ResolvedJiraImage(source_url, None, ""),  # type: ignore[arg-type]
        ResolvedJiraImage(source_url, "media-a", None),  # type: ignore[arg-type]
    ):
        with pytest.raises(TypeError):
            markdown_to_adf("plain", resolved_images=(value,))
    with pytest.raises(AdfConversionError, match="duplicate"):
        markdown_to_adf("plain", resolved_images=(resolution, resolution))
    with pytest.raises(AdfConversionError, match="unused"):
        markdown_to_adf("plain", resolved_images=(resolution,))
    with pytest.raises(AdfConversionError, match="unused"):
        markdown_to_adf(
            "![alt](https://images.test/A.png)", resolved_images=(resolution,)
        )


def test_verify_jira_media_readback_accepts_only_allowed_jira_enrichments() -> None:
    source_url = "https://images.test/a.png"
    resolution = ResolvedJiraImage(source_url, "media-a", "")
    submitted = markdown_to_adf(
        f"![alt]({source_url})\n\n![]({source_url})", resolved_images=(resolution,)
    ).value
    persisted = deepcopy(submitted)
    first_attrs = persisted["content"][0]["attrs"]
    first_attrs.update(
        {"localId": "container-local", "width": 100, "widthType": "percentage"}
    )
    first_media_attrs = persisted["content"][0]["content"][0]["attrs"]
    first_media_attrs.update(
        {
            "localId": "media-local",
            "occurrenceKey": "occurrence",
            "width": 640,
            "height": 480,
        }
    )
    persisted["content"][1]["content"][0]["attrs"]["alt"] = ""

    verify_jira_media_readback(submitted, persisted, resolved_images=(resolution,))

    changed_alt = deepcopy(persisted)
    changed_alt["content"][0]["content"][0]["attrs"]["alt"] = "changed"
    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(
            submitted, changed_alt, resolved_images=(resolution,)
        )
    assert raised.value.path == "/content/0/content/0/attrs/alt"

    moved = deepcopy(persisted)
    moved["content"].reverse()
    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(submitted, moved, resolved_images=(resolution,))
    assert raised.value.path == "/content/0/content/0/attrs/alt"

    extra = deepcopy(persisted)
    extra["content"].append(deepcopy(persisted["content"][0]))
    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(submitted, extra, resolved_images=(resolution,))
    assert raised.value.path == "/content/2/content/0"


def test_verify_jira_media_readback_wraps_schema_failure() -> None:
    source_url = "https://images.test/a.png"
    resolution = ResolvedJiraImage(source_url, "media-a", "")
    submitted = markdown_to_adf(
        f"![alt]({source_url})", resolved_images=(resolution,)
    ).value
    persisted = deepcopy(submitted)
    persisted["content"][0]["content"][0]["attrs"]["type"] = "external"

    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(submitted, persisted, resolved_images=(resolution,))
    assert raised.value.path == "/content/0"


def test_verify_jira_media_readback_rejects_ambiguous_resolution_identity() -> None:
    first_source_url = "https://images.test/a.png"
    second_source_url = "https://images.test/b.png"
    resolution = ResolvedJiraImage(first_source_url, "media-a", "")
    submitted = markdown_to_adf(
        f"![alt]({first_source_url})", resolved_images=(resolution,)
    ).value

    with pytest.raises(AdfConversionError, match="duplicate Jira media identity"):
        verify_jira_media_readback(
            submitted,
            submitted,
            resolved_images=(
                resolution,
                ResolvedJiraImage(second_source_url, "media-a", ""),
            ),
        )


def test_verify_jira_media_readback_rejects_unrepresented_identity() -> None:
    source_url = "https://images.test/a.png"
    submitted = markdown_to_adf(
        f"![alt]({source_url})",
        resolved_images=(ResolvedJiraImage(source_url, "media-a", ""),),
    ).value

    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(
            submitted,
            submitted,
            resolved_images=(ResolvedJiraImage(source_url, "wrong-media", ""),),
        )
    assert raised.value.path == ""


def test_verify_jira_media_readback_ignores_extension_parameters() -> None:
    source_url = "https://images.test/a.png"
    resolution = ResolvedJiraImage(source_url, "media-a", "")
    submitted = markdown_to_adf(
        f"![alt]({source_url})", resolved_images=(resolution,)
    ).value
    persisted = deepcopy(submitted)
    persisted["content"].append(
        {
            "type": "extension",
            "attrs": {
                "extensionKey": "test",
                "extensionType": "com.atlassian",
                "parameters": {
                    "type": "media",
                    "attrs": {
                        "type": "file",
                        "id": "media-a",
                        "collection": "",
                    },
                },
            },
        }
    )

    verify_jira_media_readback(submitted, persisted, resolved_images=(resolution,))


def test_lossy_conversion_error_annotations_are_runtime_resolvable() -> None:
    assert (
        get_type_hints(LossyConversionError.__init__)["diagnostics"]
        == Iterable[Diagnostic]
    )
