# adf-bridge

`adf-bridge` is a small, pure-Python bridge between portable GFM Markdown and
a focused Jira-oriented subset of Atlassian Document Format (ADF). It returns
ordinary JSON-compatible dictionaries rather than model classes.

```python
from adf_bridge import adf_to_markdown, markdown_to_adf

created = markdown_to_adf("Hello [~accountId:557057:User-AbC]")
assert created.value["type"] == "doc"
assert adf_to_markdown(created.value).value == "Hello [~accountId:557057:User-AbC]"
```

## API and behavior

- `markdown_image_urls(markdown, *, strict=False) -> ConversionResult[tuple[str, ...]]`
- `markdown_to_adf(markdown, *, strict=False, resolved_images=()) -> ConversionResult[AdfDocument]`
- `adf_to_markdown(document, *, strict=False) -> ConversionResult[str]`
- `validate_adf(document) -> None`
- `verify_jira_media_readback(submitted, persisted, *, resolved_images) -> None`

A `ConversionResult` holds `value` and an ordered tuple of structured
`Diagnostic` values. `strict=True` converts any readable-degradation warning
into `LossyConversionError` after conversion completes. Invalid ADF, unknown
constructs, and out-of-profile features always raise project-owned errors.

Blank CommonMark Markdown becomes the canonical sole empty root paragraph.
Empty ADF documents also render as an empty string. GFM output is canonicalized
and has no terminal newline; exact source spelling is not round-tripped.

## v0.1 profile

Direct support covers paragraphs, headings, blockquotes, lists, code blocks,
hard breaks, rules, tables, text, strong/emphasis/strike/code/link marks, and
canonical Jira account-ID mentions. A mention nested in Markdown emphasis,
strong, or strikethrough is emitted unmarked because the Jira ADF schema forbids
mention marks; this produces `markdown.mention_marks_discarded` and strict mode
rejects it. Mention IDs remain opaque; `&`, `<`, and `>` are source-encoded
safely. Adjacent marked text uses a local mark stack, so
shared presentation marks stay open across supported overlaps. Basic table-cell
paragraphs and hard breaks are flattened through exact lowercase `<br>` with one
warning per affected cell. Dates, emoji, inline cards, status, expand/panel, and
unmarked media have readable warning-producing fallbacks. Inline-code line
endings normalize to spaces with a diagnostic; code-block text canonicalizes to
LF with one trailing newline when nonempty and warns only when that changes its
semantic text.

Link, image, and card labels entity-encode their nested literal syntax, so URL
labels with Markdown punctuation round-trip without retained escape backslashes.
Inside table cells, nested syntax-owned values including mention IDs and link
titles entity-encode pipes before GFM table parsing. Form feed is entity-encoded
losslessly. Bridge-generated direct link, card, and external-media destinations
are opaque values: a reversible CommonMark entity encoding preserves their exact
supported characters without URL normalization. Caller-authored Markdown
autolinks and used reference links instead use CommonMark/Mistune URL
normalization; their raw source spelling is not an opaque-destination
preservation contract and produces no diagnostic. Ordinary and readable-fallback
text containing U+0000 normalizes to U+FFFD with a warning; mention IDs
containing U+0000 are rejected to preserve their opaque identity. Markdown
consisting only of reference definitions produces no visible ADF content and
warns with `markdown.reference_definitions_discarded`. Values containing a character that
HTML5 character references cannot preserve (such as NUL) are fatal at the
bridge-generated destination attribute. Presentation marks with an
unrepresentable Unicode-whitespace boundary (such as VT or NEL) preserve their
text but are discarded with a warning. Ordinary/root VT and NEL text remains
exact; at list or table edges a reversible source entity is used when available,
or `adf.boundary_whitespace_normalized` documents unavoidable loss. Empty link
titles and titles containing control characters are intentionally omitted with
an attribute-discard warning.

Block alignment and indentation marks, and every mark on `media`,
`mediaSingle`, or `mediaGroup`, are fatal because v0.1 has no unambiguous GFM
placement for them. Linked inline code containing `[` or `]` is also fatal:
Mistune/CommonMark cannot preserve those code-label characters exactly. A
nonterminal heading hard break and an ordered list whose generated sequence
exceeds nine-digit markers are rejected rather than silently changing block
structure. Every break in a terminal paragraph or heading hard-break run is
discarded with a warning because portable GFM has no semantic representation for
it; table-cell breaks retain their `<br>` flattening policy. A heading's literal
ATX closing-hash candidate is source-encoded to preserve trailing `#` text.
Only the canonical sole root empty paragraph represents empty visible Markdown;
other ordinary empty ADF paragraphs are fatal. The exact empty paragraph shapes
produced by GFM empty list items and table cells render as canonical empty list
markers and cells. Adjacent same-kind lists use equivalent alternating GFM
markers to remain distinct. Empty Markdown link labels, linked images, images
in headings or table cells, and unsupported table-cell shapes are rejected
rather than silently dropped.

See the [support matrix](https://github.com/en-ver/adf-bridge/blob/main/docs/support-matrix.md)
and [diagnostics guide](https://github.com/en-ver/adf-bridge/blob/main/docs/diagnostics.md)
for details. `markdown_image_urls()` uses the same focused parser as conversion
and returns supported image destinations in source order. Callers can supply
immutable `ResolvedJiraImage(source_url, media_id, collection, width=None,
height=None)` values to convert exact matching image URLs into Jira `file` media;
unmapped URLs remain external. `width` and `height` are optional, but when
supplied they must be a paired positive integer intrinsic size. Mappings are data
only: invalid, unused, duplicate-source, or duplicate Jira media-identity
(`media_id`, `collection`) entries fail, and no URL normalization or Jira
enrichment is performed. Every Markdown image becomes a centered block
`mediaSingle`. A managed image with dimensions has an exact child dimension pair
and a `width: 100`, `widthType: percentage` parent; legacy dimensionless managed
images and external images remain widthless.

Markdown owns alt text for every occurrence. Managed media cannot render back to
its original attachment-content URL. On ADF-to-Markdown conversion, nonempty
managed-media alt text is preserved as escaped readable text; absent or empty alt
renders as neutral `attachment` text. Opaque media IDs are never used in Markdown
presentation. `verify_jira_media_readback()` narrowly checks persisted managed
media at the same ADF paths, permitting Jira local IDs and occurrence keys. It
requires dimensioned managed-media parent sizing and child dimensions to persist
exactly, while allowing Jira to enrich legacy widthless submitted media with
complete parent sizing and positive integer child dimensions. This package does
not perform Jira lookups, network operations, CLI work, or plugin registration.

## Schema and licenses

The wheel bundles the exact unmodified `@atlaskit/adf-schema` 57.3.4 full JSON
Schema. It is checksum-verified, requires local-only `$ref` values, and is
compiled once with defaults disabled using `fastjsonschema`. Project code is
MIT licensed. The bundled Atlassian schema is Apache-2.0; its attribution and
full license are in
[THIRD_PARTY_NOTICES.md](https://github.com/en-ver/adf-bridge/blob/main/THIRD_PARTY_NOTICES.md).

## Development

Use [uv](https://docs.astral.sh/uv/):

```sh
uv sync --all-groups
make check-ci
```

See [CONTRIBUTING.md](https://github.com/en-ver/adf-bridge/blob/main/CONTRIBUTING.md)
for the focused validation commands.
