# Diagnostics and strict mode

Non-strict conversion returns readable output plus ordered warnings. Important
codes include `markdown.raw_html`, `markdown.task_list_degraded`,
`markdown.image_title_discarded`, `adf.status_degraded`,
`adf.media_degraded`, `adf.code_span_line_break_normalized`,
`adf.code_block_text_normalized`, `adf.presentation_mark_degraded`,
`adf.boundary_whitespace_normalized`, `adf.nul_normalized`,
`adf.terminal_hard_break_discarded`, `adf.table_cell_flattened`,
`adf.attribute_discarded`, `markdown.nul_normalized`,
`markdown.mention_marks_discarded`, and
`markdown.reference_definitions_discarded`.
ADF-to-Markdown paths are RFC 6901 JSON Pointers. Empty, duplicate, and unused
resolved-image mappings are fatal `AdfConversionError` values regardless of strict
mode; contract-shape errors raise `TypeError`. They do not add warning diagnostics.
`verify_jira_media_readback()` raises
`JiraMediaVerificationError` with the first failing RFC 6901 path rather than a
lossy-conversion diagnostic.

`adf.code_span_line_break_normalized` is emitted once for each source text node
with a code mark whose CRLF, CR, or LF is normalized to a space. Its path points
to that node's `text` member. `adf.code_block_text_normalized` is emitted once
per code block only when its combined text changes during canonical LF and
trailing-newline normalization; its path is that block's `content` member. An
empty code block is already canonical and has no diagnostic.

`adf.nul_normalized` is emitted once per ADF ordinary or readable-fallback
text member containing U+0000; its path is that member and the rendered value
uses U+FFFD as CommonMark requires. `markdown.nul_normalized` is emitted once
per Markdown input containing U+0000, before parsing, and has no JSON Pointer.
Both warnings escalate in strict mode. Mention IDs containing U+0000 are
instead fatal because their opaque identity cannot be degraded.

`markdown.mention_marks_discarded` is emitted once per recognized Jira mention
nested in Markdown emphasis, strong, or strikethrough. Jira ADF does not permit
marks on a `mention`, so conversion retains the exact account ID in an unmarked
mention node and discards the surrounding formatting. It has no JSON Pointer
and strict mode escalates it.

`adf.presentation_mark_degraded` is emitted once per source text node at its
`marks` member when an `em`, `strong`, or `strike` mark has unrepresentable
Unicode whitespace at its first or last text boundary. The text is retained
without those presentation marks. An empty ADF link `title`, or one containing a
control character (including line endings or NUL), uses one existing
`adf.attribute_discarded` diagnostic at that title member and omits only the
title. `adf.boundary_whitespace_normalized` marks whitespace at a
Markdown-sensitive source boundary where plain literal preservation is not
guaranteed. The renderer may source-encode it or apply and readably expose
normalization; some values may nevertheless round-trip with the current
parser. At hardBreak-created source-line boundaries, the diagnostic is emitted
when context-sensitive encoding or handling is required. Exact encoding alone
at ordinary outer list-item, table-cell, or blockquote boundaries does not emit
the diagnostic. The readable result is returned and strict mode escalates the
warning. `adf.terminal_hard_break_discarded`
is emitted at every `hardBreak` node in a terminal paragraph or heading run
because portable GFM cannot preserve it; the nodes are omitted and strict mode
escalates each warning. This applies at every block-composition position,
including lists and blockquotes, but not table cells: they retain the
`adf.table_cell_flattened` `<br>` policy.
`adf.table_cell_flattened` is emitted once per affected source table cell, before
diagnostics for flattened child metadata; it covers either multiple paragraphs
or a hard break lowered through `<br>`. `markdown.reference_definitions_discarded`
is emitted once when Markdown contains reference definitions but no visible
block; the definitions have no ADF representation and strict mode escalates the
warning. Used reference links remain ordinary parser normalization without this
diagnostic.

```python
from adf_bridge import LossyConversionError, adf_to_markdown

try:
    adf_to_markdown(document, strict=True)
except LossyConversionError as error:
    for diagnostic in error.diagnostics:
        print(diagnostic.code, diagnostic.path)
```

`strict=True` escalates every warning after conversion. It does not make invalid
or unsupported inputs recoverable: those raise their corresponding
project-owned error regardless of strict mode. In particular, block alignment
and indentation marks, all media/media-container marks, nonterminal heading
hard breaks, and ordered-list sequences that would generate a ten-digit marker are fatal
profile errors, not discard diagnostics. Other than the canonical sole root empty paragraph, root and ordinary empty ADF
paragraphs, empty Markdown blockquotes, ADF blockquotes with empty,
whitespace-only, or empty-rendering children, and bridge-generated destinations
containing a character that cannot be represented by an exact HTML5 character
reference are likewise fatal profile boundaries. The exact empty paragraph
shapes owned by empty GFM list items and table cells render canonically without
a diagnostic.
