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


def test_dimensioned_managed_images_have_full_width_parent_at_root() -> None:
    source_url = "https://jira.test/rest/api/3/attachment/content/42"
    resolution = ResolvedJiraImage(source_url, "media-42", "", 640, 480)
    result = markdown_to_adf(
        f"![first]({source_url})\n\n![second]({source_url})\n\n![outside](https://x.test/a)",
        resolved_images=(resolution,),
    )

    first, second, external = result.value["content"]
    assert first == {
        "type": "mediaSingle",
        "attrs": {"layout": "center", "width": 100, "widthType": "percentage"},
        "content": [
            {
                "type": "media",
                "attrs": {
                    "type": "file",
                    "id": "media-42",
                    "collection": "",
                    "width": 640,
                    "height": 480,
                    "alt": "first",
                },
            }
        ],
    }
    assert second["attrs"] == first["attrs"]
    assert second["content"][0]["attrs"] == {
        "type": "file",
        "id": "media-42",
        "collection": "",
        "width": 640,
        "height": 480,
        "alt": "second",
    }
    assert external["attrs"] == {"layout": "center"}
    assert external["content"][0]["attrs"] == {
        "type": "external",
        "url": "https://x.test/a",
        "alt": "outside",
    }


def test_dimensioned_managed_images_preserve_list_block_structure() -> None:
    source_url = "https://jira.test/rest/api/3/attachment/content/42"
    result = markdown_to_adf(
        f"- Bullet text\n\n  ![diagram]({source_url})",
        resolved_images=(ResolvedJiraImage(source_url, "media-42", "", 640, 480),),
    )

    list_item = result.value["content"][0]["content"][0]
    assert [block["type"] for block in list_item["content"]] == [
        "paragraph",
        "mediaSingle",
    ]
    media_single = list_item["content"][1]
    assert media_single["attrs"] == {
        "layout": "center",
        "width": 100,
        "widthType": "percentage",
    }
    assert media_single["content"][0]["attrs"] == {
        "type": "file",
        "id": "media-42",
        "collection": "",
        "width": 640,
        "height": 480,
        "alt": "diagram",
    }


def test_legacy_managed_images_remain_centered_and_widthless() -> None:
    source_url = "https://jira.test/rest/api/3/attachment/content/42"
    result = markdown_to_adf(
        f"![diagram]({source_url})",
        resolved_images=(ResolvedJiraImage(source_url, "media-42", ""),),
    )

    assert result.value["content"][0] == {
        "type": "mediaSingle",
        "attrs": {"layout": "center"},
        "content": [
            {
                "type": "media",
                "attrs": {
                    "type": "file",
                    "id": "media-42",
                    "collection": "",
                    "alt": "diagram",
                },
            }
        ],
    }


@pytest.mark.parametrize(
    ("width", "height", "error"),
    [
        (None, 480, AdfConversionError),
        (640, None, AdfConversionError),
        (True, 480, TypeError),
        (640, False, TypeError),
        (640.0, 480, TypeError),
        (640, 480.0, TypeError),
        (0, 480, AdfConversionError),
        (640, -1, AdfConversionError),
    ],
)
def test_resolved_image_dimensions_must_be_paired_positive_integers(
    width: object, height: object, error: type[Exception]
) -> None:
    source_url = "https://images.test/a.png"

    with pytest.raises(error):
        markdown_to_adf(
            f"![alt]({source_url})",
            resolved_images=(
                ResolvedJiraImage(  # type: ignore[arg-type]
                    source_url, "media-a", "", width, height
                ),
            ),
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


def test_verify_jira_media_readback_allows_legacy_widthless_enrichments() -> None:
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

    partial_dimensions = deepcopy(persisted)
    partial_dimensions["content"][0]["content"][0]["attrs"].pop("height")
    with pytest.raises(JiraMediaVerificationError):
        verify_jira_media_readback(
            submitted, partial_dimensions, resolved_images=(resolution,)
        )

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


def test_verify_jira_media_readback_requires_dimensioned_values_to_persist() -> None:
    source_url = "https://images.test/a.png"
    resolution = ResolvedJiraImage(source_url, "media-a", "", 640, 480)
    submitted = markdown_to_adf(
        f"![alt]({source_url})", resolved_images=(resolution,)
    ).value
    persisted = deepcopy(submitted)
    persisted["content"][0]["attrs"]["localId"] = "container-local"
    persisted["content"][0]["content"][0]["attrs"].update(
        {"localId": "media-local", "occurrenceKey": "occurrence"}
    )

    verify_jira_media_readback(submitted, persisted, resolved_images=(resolution,))

    changed_parent_width = deepcopy(persisted)
    changed_parent_width["content"][0]["attrs"]["width"] = 99
    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(
            submitted, changed_parent_width, resolved_images=(resolution,)
        )
    assert raised.value.path == "/content/0/attrs/width"

    changed_parent_width_type = deepcopy(persisted)
    changed_parent_width_type["content"][0]["attrs"]["widthType"] = "pixel"
    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(
            submitted, changed_parent_width_type, resolved_images=(resolution,)
        )
    assert raised.value.path == "/content/0/attrs/widthType"

    non_integer_parent_width = deepcopy(persisted)
    non_integer_parent_width["content"][0]["attrs"]["width"] = 100.0
    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(
            submitted, non_integer_parent_width, resolved_images=(resolution,)
        )
    assert raised.value.path == "/content/0/attrs/width"

    missing_child_dimensions = deepcopy(persisted)
    missing_child_dimensions["content"][0]["content"][0]["attrs"].pop("width")
    missing_child_dimensions["content"][0]["content"][0]["attrs"].pop("height")
    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(
            submitted, missing_child_dimensions, resolved_images=(resolution,)
        )
    assert raised.value.path == "/content/0/content/0/attrs/width"

    changed_child_dimensions = deepcopy(persisted)
    changed_child_dimensions["content"][0]["content"][0]["attrs"]["width"] = 639
    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(
            submitted, changed_child_dimensions, resolved_images=(resolution,)
        )
    assert raised.value.path == "/content/0/content/0/attrs"

    for value in (0, 640.0, True):
        invalid_child_dimension = deepcopy(persisted)
        invalid_child_dimension["content"][0]["content"][0]["attrs"]["width"] = value
        with pytest.raises(JiraMediaVerificationError):
            verify_jira_media_readback(
                submitted, invalid_child_dimension, resolved_images=(resolution,)
            )

    invalid_submitted_dimensions = deepcopy(submitted)
    invalid_submitted_dimensions["content"][0]["content"][0]["attrs"]["width"] = 639
    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(
            invalid_submitted_dimensions,
            invalid_submitted_dimensions,
            resolved_images=(resolution,),
        )
    assert raised.value.path == "/content/0/content/0/attrs"


def _exception_graph(error: BaseException) -> tuple[BaseException, ...]:
    pending = [error]
    seen: set[int] = set()
    graph: list[BaseException] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        graph.append(current)
        pending.extend(
            exception
            for exception in (current.__cause__, current.__context__)
            if exception is not None
        )
    return tuple(graph)


@pytest.mark.parametrize("label", ("submitted", "persisted"))
def test_verify_jira_media_readback_sanitizes_schema_failures(label: str) -> None:
    source_url = "https://images.test/a.png"
    opaque_media_id = "opaque-media-id"
    resolution = ResolvedJiraImage(source_url, opaque_media_id, "")
    submitted = markdown_to_adf(
        f"![alt]({source_url})", resolved_images=(resolution,)
    ).value
    persisted = deepcopy(submitted)
    document = submitted if label == "submitted" else persisted
    document["content"][0]["content"][0]["attrs"]["width"] = "invalid"

    with pytest.raises(JiraMediaVerificationError) as raised:
        verify_jira_media_readback(submitted, persisted, resolved_images=(resolution,))

    assert str(raised.value) == f"{label} ADF fails schema validation"
    graph = _exception_graph(raised.value)
    assert graph == (raised.value,)
    assert all(
        opaque_media_id not in str(error) and opaque_media_id not in repr(vars(error))
        for error in graph
    )


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
