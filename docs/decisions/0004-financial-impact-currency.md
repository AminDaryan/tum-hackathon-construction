# 0004: A financial impact exists only in an explicit currency

Status: accepted.

## Context

`FinancialImpact.currency` was optional, while the data model said an impact exists only in an
explicit currency. Impacts without a currency could be added across currencies by the API or
the frontend, and a detector using its own helper could attach no currency where another
detector attached one from a currency column.

## Decision

* `FinancialImpact.currency` is required (ISO 4217).
* The explicit currency of a row comes from one accessor, `ValidationContext.currency_evidence`:
  markers on the cells, currency codes in the column headers and the row's currency column.
  Conflicting or unreadable evidence gives no currency. There is no default currency.
* Without an explicit currency, detectors leave the impact out. The difference itself stays in
  the observed and expected values and in the typed calculation.
* Summaries add impacts per currency only.
