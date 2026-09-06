# Schema and security

Validation uses the unmodified full JSON Schema from official npm package
`@atlaskit/adf-schema` 57.3.4. Its provenance, source URLs, SHA-256, Draft 4
status, and license are bundled in `adf_bridge/data/schema-provenance.json`.
The package checks the checksum and that every `$ref` is local before compiling
the fixed schema once with `fastjsonschema` and `use_default=False`.

No caller can supply a schema. This matters because schema resolvers may fetch
remote references; the reviewed resource has only local fragments. Validation
never applies schema defaults or mutates the supplied document. Cyclic,
non-JSON, non-finite, and excessively nested values fail with project-owned
validation errors before schema compilation can process them.

Rendered literal text uses context-specific escaping and reversible source
encoding at inline semantic boundaries, so adjacent fragments cannot form new
Markdown syntax. Adjacent marked text is composed by a renderer-local mark stack
that retains shared marks and only closes or opens changed marks, avoiding
literal delimiter sequences at supported mark overlaps. Literal ATX
closing-hash candidates are source-encoded at heading ownership. CommonMark-
trimmed boundary whitespace and line endings are encoded losslessly; form feed
is numeric-entity encoded, while ordinary/root unmarked non-CommonMark
whitespace remains literal when Markdown can represent it. At list-item and
table-cell boundaries, an exact source entity is used when available; otherwise
the readable trim is diagnosed at the source text pointer. Presentation marks
whose Unicode-whitespace boundary cannot be source-encoded exactly are
intentionally discarded with a warning while retaining their text. Mention IDs
encode `&`, `<`, and `>` at the source boundary, and parsing decodes exactly one
complete entity-reference layer before applying the opaque-ID rules.

Link, image, and card labels have their own entity encoding for nested Markdown
punctuation, preventing URL-shaped labels from retaining escape backslashes.
Table-cell mention IDs and link titles source-encode `|` before table parsing;
other supported inline fallback text already passes through the contextual
literal encoder. Linked code containing `[` or `]` is rejected because those code-label
characters cannot round-trip exactly through Mistune/CommonMark.
Bridge-generated direct link, card, and external-media destinations are opaque
values, not URLs to normalize. Their Markdown angle-destination source uses
reversible numeric character references for values such as brackets, spaces,
Unicode, angle brackets, backslashes, and entity-like text; parsing reverses
that source encoding without percent-quoting. Caller-authored Markdown autolinks
and used reference links use CommonMark/Mistune URL normalization instead: their
raw source spelling is not preserved and this ordinary parser behavior produces
no diagnostic. Markdown with only reference definitions has no visible ADF
representation and emits `markdown.reference_definitions_discarded`. A
bridge-generated destination character whose HTML5
reference would not decode exactly (for example NUL or an invalid control) is
rejected at its attribute pointer rather than rewritten or dropped. Empty link titles and titles with control characters
(including NUL and line endings) are deliberately omitted with one
attribute-discard diagnostic, preserving the outer link. Every break in a
terminal paragraph or heading hard-break run is discarded with its own
diagnostic because portable GFM has no semantic representation for it; a
nonterminal heading hard break and ordinary empty ADF paragraphs are fatal
profile boundaries. The canonical sole root empty paragraph, and the exact empty
paragraph shapes owned by empty GFM list items and table cells, render
canonically without a diagnostic. Terminal table-cell breaks retain the `<br>`
flattening policy. Ordered-list rendering rejects a sequence
before any marker exceeds CommonMark's nine-digit limit; adjacent same-kind
lists alternate equivalent markers to preserve their block boundary. This
serialization is not a URL trust policy: downstream HTML renderers still need an
appropriate URL-scheme policy and HTML sanitization.
Unsafe code-fence language strings are omitted with a diagnostic rather than
being interpolated into Markdown. Code-block text uses the Mistune fence
canonicalization (LF and a trailing newline when nonempty), warning only when
that changes the source text.

Only exact lowercase `<br>` inside a GFM table cell is recognized as an ADF
`hardBreak`. Other HTML spellings, attributes, and every `<br>` outside a table
remain literal raw HTML text with a diagnostic. The Atlassian schema is
Apache-2.0 and its attribution/full license are kept in
`THIRD_PARTY_NOTICES.md`; adf-bridge source is MIT licensed.
