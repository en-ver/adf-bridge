# API

```python
from adf_bridge import (
    ResolvedJiraImage,
    adf_to_markdown,
    markdown_image_urls,
    markdown_to_adf,
    validate_adf,
    verify_jira_media_readback,
)

image_urls = markdown_image_urls("![diagram](https://jira.test/content/42)").value
resolution = ResolvedJiraImage(image_urls[0], "media-id", "")
result = markdown_to_adf("![diagram](https://jira.test/content/42)", resolved_images=(resolution,))
validate_adf(result.value)
verify_jira_media_readback(result.value, result.value, resolved_images=(resolution,))
markdown = adf_to_markdown(result.value).value
```

`Diagnostic` has stable `code`, `severity`, `path`, `keyword`, and
`schema_path` fields. Messages are explanatory rather than a text-stability
contract. Schema failures raise `AdfValidationError`; package-resource or
trusted-schema failures raise `AdfSchemaError`; profile failures raise
`AdfConversionError`; strict loss raises `LossyConversionError`.

Mentions map without lookup: `[~accountId:<id>]` becomes a `mention` node with
only `attrs.id`, and renders back with the canonical `accountId` label. Markdown
emphasis, strong, or strikethrough around a recognized mention is discarded
because the Jira ADF schema does not permit mention marks; non-strict conversion
returns the unmarked mention with one `markdown.mention_marks_discarded` warning,
and strict mode raises `LossyConversionError`. IDs are opaque and may contain
`&`, `<`, `>`, and `|`; the renderer source-encodes those characters as needed
(including `|` in table cells) and the parser decodes one complete
entity-reference layer before validating the ID. IDs containing whitespace,
backslashes, `]`, or U+0000 cannot be represented and fail; identity is never
normalized.

`markdown_image_urls()` performs the same parsing and profile validation as
`markdown_to_adf()` and returns image destinations in source order, including
repetitions and used reference images. It has the same diagnostics and strict-mode
behavior. `resolved_images` is a keyword-only sequence of immutable
`ResolvedJiraImage` values. Its source URLs match parser destinations exactly;
`source_url` and `media_id` must be nonempty, while `collection` may be empty.
Duplicate source URLs, duplicate Jira media identities (the same `media_id` and
`collection`), and unused mappings raise `AdfConversionError`; a non-sequence,
wrong item type, or wrong field type raises `TypeError`.
A match produces a `mediaSingle` containing `file` media with only its resolved
ID, collection, and that Markdown occurrence's nonempty alt text. The bridge does
not look up URLs or add Jira presentation attributes.

`verify_jira_media_readback()` schema-validates submitted and persisted documents
then compares only resolved file-media occurrences. It requires the same paths,
identity, layout, and alt text, rejects extra occurrences and structural changes,
and permits only Jira local IDs, a complete sizing pair, occurrence keys, and
nonnegative media dimensions. Resolution mappings must have unique source URLs
and Jira media identities; invalid mappings raise `AdfConversionError`. Otherwise,
it raises `JiraMediaVerificationError` with the first failing RFC 6901 path. This
is persistence verification, not a rendering or whole-document equality assertion.
