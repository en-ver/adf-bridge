# Changelog

## Unreleased

- Add optional paired intrinsic dimensions to `ResolvedJiraImage`. Dimensioned
  managed images now receive exact child dimensions and centered 100% parent
  sizing; legacy dimensionless managed images and external images remain
  widthless. Readback verification preserves the dimensioned structure while
  retaining documented Jira enrichment compatibility for legacy images.

## 0.1.2 - 2026-09-07

- Preserve Jira account-ID mentions nested in Markdown emphasis, strong, or
  strikethrough as unmarked mentions, with a strict-mode diagnostic because the
  Jira ADF schema does not permit mention marks.

## 0.1.1 - 2026-09-06

- Render managed `file` and `link` media without an alt as neutral
  `attachment` text; opaque media IDs are never included in Markdown output.

## 0.1.0 - 2026-09-06

Initial focused Jira/GFM bridge with bundled ADF schema validation, structured
diagnostics, and canonical account-ID mentions. Adds no-network managed Jira
image resolution data, image URL discovery, and strict persisted-media readback
verification.
