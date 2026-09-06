# adf-bridge

`adf-bridge` converts between portable GFM Markdown and a deliberately narrow
Jira ADF profile. It has no Jira client, network access, CLI, plugins, or
public exhaustive ADF model hierarchy.

Use `markdown_to_adf()` to produce JSON-compatible ADF dictionaries and
`adf_to_markdown()` to render them. Both return a `ConversionResult`; inspect
its structured diagnostics or use `strict=True` to reject designed loss.
