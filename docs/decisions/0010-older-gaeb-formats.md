# 0010: GAEB DA XML 3.1 and 3.2, X86, and GAEB 90

Status: accepted. Extends [0009](0009-gaeb-import.md).

## Context

ADR 0009 accepted only GAEB DA XML 3.3. The sample bills of the hackathon dataset
(`Sample BoQ Dataset/`) showed what AVA programs export in practice: none of its GAEB files was
3.3. Three are DA XML 3.2 (ORCA AVA, ARCHITEXT Pallas), one is DA XML 3.1 (CaliforniaX), and
five are GAEB 90 (`.d83`, `.d84`, `.d86`), the fixed-column text format that DA XML replaced
but that is still exported, including the contract award phase 86. Every one of them was
stored as failed with "only version 3.3 is read".

## Decision

* **DA XML 3.1 (2009-12) and 3.2 (2013-10)** are read like 3.3: each file is validated against
  its own unchanged official schema, bundled in `xsd/3.1/` and `xsd/3.2/` and pinned by SHA-256.
  3.1 has one namespace for every phase (`.../GAEB_DA_XML/200407`), so its phase is taken from
  `Award/DP`. The 3.1 schemas import the W3C schemas `xml.xsd` and `xmldsig-core-schema.xsd`;
  they are bundled and pinned as well, and compiled without loading the DTD the signature schema
  names, so nothing is fetched from the network. 3.0 and older are rejected with a reason.
* **Phase 86 (Auftragserteilung, contract award)** is read in every version. It carries the
  item flags of the call for bids and the agreed prices, so its items count toward totals as
  in X81/X83 (only X84/D84 bids leave that open).
* **GAEB 90** (`.d81`, `.d83`, `.d84`, `.d86`) is read by `ingestion/gaeb/gaeb90.py` into the
  same `GaebDocument` the XML reader produces, so flattening, the declared structure and every
  detector work unchanged. There is no official schema; the reader checks instead: the file
  starts with record `00` (or `T0` for contract terms), every line is a record of at most 80
  characters with a record type, record `00` states the phase the extension names and a valid
  OZ mask, numeric fields are digits, and record `99` closes the file. The record layout (in the
  module docstring) follows the GAEB 90 rules as documented with worked examples in "Das freie
  GAEB Buch" (MWM, V 3.9.1) and was checked field by field against the dataset: the D83 and the
  X83 of the same bill (8209.003) give the same items, quantities and units, and every priced
  file reconciles its item totals and category subtotals.
* **GAEB 90 specifics.** Values are fixed-decimal digits written out as decimal text (a unit
  price with a tenth of a cent keeps three decimals). Categories come from the OZ mask, so a D84
  that states only prices (no category records) still gets its categories and subtotals.
  The character set is code page 850 as prescribed; files written in Windows-1252 are
  recognised by their umlauts and the choice is recorded in the extraction details (`encoding`).
  An item number that does not fit the mask (letters outside the index) is kept as written
  where its records place it, with a review warning (`gaeb90_invalid_item_number`). A zero bill
  total in record `99` is not shown (programs leave it unfilled). Unit-price components
  (record 30) and contract terms (T records) are kept in the file but not shown, and counted in
  `gaeb_elements_not_shown`. Cell sources have the kind `gaeb_90` (row, column, file line).

## Consequences

* All nine GAEB files of the sample dataset are read; `tests/unit/ingestion/test_gaeb90.py`
  checks each of them when the dataset folder is present, plus self-made fixtures
  (`small.d83`, `small.d84`, `small.d86`, `small.x86`) that are always present.
* What GAEB 90 cannot state is missing: category labels are cut at 40 characters by some
  programs, and lump-sum items carry no flag (only the unit `psch` shows them).
* Still out of scope: GAEB 2000 (`.p83`), DA XML 3.1 files of the 2007-11 schema release (they
  fail the 2009-12 schema with the line named), phases 82, 85 and 87, and PDF bills.
