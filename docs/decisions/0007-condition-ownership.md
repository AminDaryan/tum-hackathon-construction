# 0007: Each cell condition has exactly one reporting detector

Status: accepted.

## Context

A single `#REF!` in a line total would have been reported by the line total, subtotal, grand
total and required-values checks: four findings, four dismissals, inflated counts.

## Decision

`app/validation/contracts/conditions.py` classifies cells (`cell_condition`) and assigns each
condition that is a finding by itself one owner: errors and unavailable formula results to
`formula_errors`, ambiguous and failed parses to `data_type_conformance`, required empty values
to `required_values`, low confidence and structural uncertainty to `extraction_quality`. Every
other detector abstains on such inputs and counts them under the standard coverage keys. The
table is in `docs/architecture/validation-engine.md`.
