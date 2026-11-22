# 0009: GAEB DA XML import

Status: accepted. Extended by [0010](0010-older-gaeb-formats.md): DA XML 3.1 and 3.2, phase
86, and GAEB 90 are read as well.

## Context

German bills of quantities are exchanged as GAEB DA XML. The phase of the exchange is part of
the format: X81 is the bill of quantities, X83 the call for bids, X84 the bid. A GAEB file
states its structure (categories, items, totals, standard text keys) in XML elements; nothing
has to be guessed from headers. The workbench must read these files strictly, so that a file
it accepts is a file the official schema accepts.

## Decision

* **Version and phases.** GAEB DA XML 3.3 (schema release 2021-05) in the phases 81, 83 and 84
  (`DP` 84 or 84Z). Other versions, other phases and GAEB 90 / 2000 are rejected with a reason.
  The extension names the phase; namespace, `GAEBInfo/Version` and `Award/DP` must agree with
  it.
* **Strict validation.** Each file is validated against the unchanged official XSD files in
  `backend/app/ingestion/gaeb/xsd/3.3/`, pinned by SHA-256 and compiled offline. A changed
  schema file is refused; no schema is fetched from the network. XML with a DOCTYPE is refused
  before parsing (no entity expansion). Schema errors name the XML line.
* **One adapter package.** `ingestion/gaeb/` (`schemas`, `reader`, `model`, `flatten`,
  `adapter`) is the only code that knows GAEB. It produces the same `RawWorkbook` as the
  spreadsheet adapters: one table whose rows are the bill's categories, items and totals, each
  cell with a `gaeb_xml` source (row, column and XML line).
* **Declared structure.** The adapter fills `RawSheet.declared` (a `TableDecisions`) with the
  row kinds, section levels, `counts_toward_totals` and the column mapping the file states.
  Normalization lays reviewer decisions over it (`TableDecisions.over`): a reviewer still wins.
  Rows decided by the file carry rule `declared`, a reviewer's rule `user`.
* **Fields only a structure can map.** Profile fields with `match_headers: false`
  (`standard_text_key`, `standard_text_catalog`) are never matched from
  spreadsheet headers, so the new fields cannot change how existing spreadsheets are mapped.
  Amendment (BoQ 1.8.0, #76): `discount_percent` also maps the exact percentage headers
  `Nachlass %`, `Positionsnachlass %`, `item discount %`; unqualified or fuzzy aliases do not
  map. Declared and reviewer mappings still take precedence.
* **Discounts.** `deterministic.line_total` applies an item discount the GAEB way:
  `round(round(q × p, 2) × (1 − d), 2)` (Fachdokumentation 4.6.17).
* **STLB-Bau.** `domain.standard_text_keys` compares items of the same file that share a
  standard text key (units, unit prices, catalogue versions). The texts are not compared with
  the DIN catalogue, which is licensed; every run says so in a note.

## Consequences

* A new GAEB version or phase is its XSD files plus one `GaebSchema` entry; nothing outside the
  package changes. Another self-describing format follows the same seam (`RawSheet.declared`).
* The official BVBS test files are not committed (their redistribution terms are unknown). Self-made
  fixtures in `backend/tests/fixtures/gaeb/` pass the schema; the BVBS files are tested locally
  when `TWB_GAEB_SAMPLES` names their folder.
* Sub-descriptions (`SubDescr`) and their keys are not shown as rows; item attachments, BoQ
  text blocks other than item descriptions, and GAEB export are out of scope.
