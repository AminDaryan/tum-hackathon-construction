# 0002: Hidden sheets

Status: accepted.

## Context

Workbooks hide sheets for lookup tables, price databases and calculation helpers, but a hidden
sheet can also hold data that a visible total depends on, or content someone did not want a
reviewer to see. Hidden rows are already kept (they may belong to a total); hidden sheets were
dropped by the first ingestion draft without a trace.

## Decision

* Ingestion extracts every worksheet, hidden or not, and records `RawSheet.hidden`. The format
  layer never drops data.
* Normalization skips hidden sheets by default and records the informational warning
  `hidden_sheet_skipped` naming the sheet, so the reviewer sees that it exists.
* A reviewer includes a hidden sheet with `TableDecisions(sheet_index=…, include_hidden_sheet=True)`;
  the table is then normalized like any other and its `source` keeps the sheet name.

## Consequences

Validation focuses on what the document presents, nothing is lost, and the decision is visible
and reversible.
