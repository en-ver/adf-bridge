# Contributing

Use Python 3.11+ and uv. Keep changes focused on the documented v0.1 profile;
do not add a profile registry, network integration, or public ADF model layer.

```sh
uv sync --all-groups
make check-ci
```

Before changing the bundled schema, update it and `schema-provenance.json`
together, retain the Atlassian notice, verify its SHA-256 and local-only
references, and review resulting validation/profile changes.
