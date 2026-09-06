# API

```python
from adf_bridge import adf_to_markdown, markdown_to_adf, validate_adf

result = markdown_to_adf("Hello **ADF**")
validate_adf(result.value)
markdown = adf_to_markdown(result.value).value
```

`Diagnostic` has stable `code`, `severity`, `path`, `keyword`, and
`schema_path` fields. Messages are explanatory rather than a text-stability
contract. Schema failures raise `AdfValidationError`; package-resource or
trusted-schema failures raise `AdfSchemaError`; profile failures raise
`AdfConversionError`; strict loss raises `LossyConversionError`.

Mentions map without lookup: `[~accountId:<id>]` becomes a `mention` node with
only `attrs.id`, and renders back with the canonical `accountId` label. IDs are
opaque and may contain `&`, `<`, `>`, and `|`; the renderer source-encodes those
characters as needed (including `|` in table cells) and the parser decodes one
complete entity-reference layer before validating the ID. IDs containing
whitespace, backslashes, `]`, or U+0000 cannot be represented and fail;
identity is never normalized.
