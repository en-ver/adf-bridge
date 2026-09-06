# Support matrix

| Policy | ADF features |
| --- | --- |
| Direct | `doc`, nonempty paragraphs plus the canonical sole root/list-item/table-cell empty paragraph shapes, headings without nonterminal hard breaks, blockquotes with visible children, bullet/ordered lists within the nine-digit marker limit, list items, code blocks, nonterminal paragraph hard breaks, rules, basic tables, text, `strong`, `em`, `strike`, `code`, and `link` |
| Jira syntax | User `mention` as `[~accountId:<id>]` |
| Readable degradation | `date`, `emoji`, `inlineCard`, `status`, `expand`, `nestedExpand`, `panel`, unmarked `media`, `mediaSingle`, and `mediaGroup`; colors, underline, subsuperscript, and listed presentation metadata; presentation marks at unrepresentable Unicode-whitespace boundaries; inline-code and code-block text normalization; empty or control-character link-title discard; list/table/blockquote boundary-whitespace normalization; terminal paragraph/heading hard-break-run discard; table-cell flattening; reference-definition-only Markdown discard |
| Fatal | Unknown or out-of-profile schema nodes/marks, task/decision/layout/extension families, `mediaInline`, block alignment and indentation marks, every media/media-container mark, unsafe mention IDs, bridge-generated link/card/external-media destinations with HTML5-character-reference-invalid values, linked inline code containing `[` or `]`, nonterminal heading hard breaks, empty Markdown blockquotes, empty or whitespace-only ADF blockquote paragraphs, blockquote children that render empty, ordinary empty ADF paragraphs other than the canonical sole root/list-item/table-cell shapes, ordered-list sequences with ten-digit markers, empty Markdown link labels, linked Markdown images, unrepresentable cards, and unsupported table-cell shapes |

Markdown supports CommonMark blocks/inlines plus GFM tables, strikethrough,
URL autolinks, and task-list recognition. Task state is visible `[ ]`/`[x]`
text with a warning; raw HTML is literal text with a warning. Inline images are promoted to external `mediaSingle` nodes unless an exact
caller-supplied `ResolvedJiraImage.source_url` selects managed `file` media.
Managed nodes retain the same centered layout and per-occurrence Markdown alt
text, without authored dimensions, title, local ID, or occurrence key. Image
promotion warns when surrounding inline layout changes or an image title is
discarded. Their soft and hard alt-text breaks normalize to spaces. Images in
headings and table cells fail
intentionally rather than producing invalid ADF. Linked Markdown images fail
because v0.1 defines no canonical media-mark placement.

Table cells accept nonempty paragraphs and the sole empty paragraph generated
for an empty GFM cell. Multiple paragraphs and ADF `hardBreak` nodes lower to
exact lowercase `<br>` tokens and emit one
`adf.table_cell_flattened` warning for the source cell; other cell block shapes
and code text with a backslash before a pipe are fatal. Literal heading text
that ends in an ATX closing-hash candidate is source-encoded to preserve its
trailing `#`. A nonterminal heading `hardBreak` is fatal. Every `hardBreak` in a
terminal paragraph or heading run is
discarded with an `adf.terminal_hard_break_discarded` warning at that node,
whether it occurs at the root, in a list or quote, or before or after other
blocks; strict mode escalates every warning. Terminal table-cell breaks retain
`<br>` flattening instead. Only the exact sole root empty paragraph and the empty
paragraph shapes owned by empty GFM list items and table cells render canonically
without a diagnostic; other ordinary empty ADF paragraphs are fatal. Empty
Markdown blockquotes and ADF blockquotes with an empty, whitespace-only, or
otherwise empty-rendering child are outside the profile so that trimmed content
cannot be canonicalized as an empty quote.
Adjacent same-kind lists alternate `-`/`*` or `.`/`)` at their shared block
boundary so they do not merge; ordered rendering rejects a sequence before any
marker would exceed nine digits. Only exact lowercase `<br>` inside a GFM table
cell parses back to an ADF `hardBreak`. `<BR>`,
`<br/>`, attributed variants, and `<br>` outside a table remain literal raw
HTML text with the normal raw-HTML warning.

Ordinary/root text preserves CommonMark-trimmed boundary whitespace and line
endings with reversible character references. U+0000 in ordinary or readable
fallback text normalizes to U+FFFD with `adf.nul_normalized` at the source ADF
member; Markdown input receives one `markdown.nul_normalized` warning. Form
feed is entity-encoded so it round-trips losslessly, while unmarked
non-CommonMark whitespace (including VT
and NEL) remains text even when Mistune would otherwise treat an all-whitespace
source as blank. At list-item and table-cell text boundaries, a reversible character reference
is used when available; otherwise the readable trimmed result has one
`adf.boundary_whitespace_normalized` warning at the source text pointer. The
same rule applies at both boundaries of every nonempty blockquote paragraph
and each inline source-line segment separated by a hard break, including
intermediate children. Source-encoded non-CommonMark whitespace at an inline
source-line boundary also produces the diagnostic, so strict mode records the
boundary-sensitive representation. `em`, `strong`, and `strike` whose first or last character is Unicode
whitespace that cannot be source-encoded exactly (for example VT or NEL) are lowered to unmarked text with one
`adf.presentation_mark_degraded` warning per source text node. Inline-code
CRLF, CR, and LF normalize to spaces and produce a warning. Code-block text
canonicalizes to LF with one trailing newline when nonempty and produces one
`adf.code_block_text_normalized` warning per changed source code block. The
empty code block uses the canonical empty fence without a warning. Code-fence
languages are retained when they are single tokens without controls, backticks,
or angle brackets; other values are discarded with a diagnostic.

Link, image, and card labels entity-encode literal Markdown punctuation within
their nested label syntax, so URL-shaped labels do not retain backslashes after
parsing. Table-cell mention IDs and link titles likewise source-encode `|` so
nested syntax cannot split a GFM row. Bridge-generated direct link, card, and
external-media destinations use reversible CommonMark character references
rather than URL percent-normalization, preserving opaque values such as IPv6
brackets, spaces, Unicode, angle brackets, backslashes, and entity-like text
exactly. Caller-authored Markdown autolinks and used reference links instead
accept CommonMark/Mistune URL normalization as Markdown semantics; their raw
source spelling is not preserved and this produces no diagnostic. Markdown with
only reference definitions has no ADF-visible content and emits
`markdown.reference_definitions_discarded` (including in strict mode). Values
whose HTML5 character reference would
not decode exactly, including NUL and invalid controls, are fatal at the
bridge-generated destination attribute. Mention IDs containing NUL are fatal
rather than normalized, preserving their opaque identity. Link titles explicitly
set to `""` or containing control characters
(including line endings and NUL) are omitted and emit one normal
attribute-discard warning at their title pointer. Linked code with `[` or `]` is
fatal because a portable Mistune/CommonMark label cannot preserve those code
characters exactly.
