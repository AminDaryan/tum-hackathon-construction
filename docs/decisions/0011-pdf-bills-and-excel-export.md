# 0011: Printed bills from PDF, and the Excel export

Status: accepted. Takes the PDF text-layer import out of [0008](0008-deferred-to-phase-2.md).
Extended by [0012](0012-ocr-for-scanned-pdfs.md): scanned pages are read by OCR.

## Context

Most bills in the hackathon dataset (`Sample BoQ Dataset/`) arrive as PDF: 34 printed
Leistungsverzeichnisse from at least six AVA programs, often with the tender forms bound in
front. All of them have a text layer; none is a scan. Reviewers want the table out of the PDF
and in Excel, and the same checks run on it as on a GAEB file.

Generic table extractors were weighed against a reader built for the bill's layout. Ruled-table
tools (Camelot, pdfplumber's table finder) need drawn cell borders, which LV printouts do not
have; layout models (Docling and similar) are large, slow on CPU and still return rows of
text, not items with a quantity, unit and prices. A printed bill, however, always has the same
grammar: a column header row on every page, an ordinal number (OZ) in the left column, text,
and one line with quantity, unit, unit price and total. Six of the dataset's PDFs also exist as
GAEB files, which gives exact ground truth.

## Decision

* **Reader.** `ingestion/pdf/`: `layout` reads the text layer with PDFium (pypdfium2) into
  positioned words and lines; `bill` finds the bill's columns from its header row and reads
  blocks (OZ, text, quantity line, ``Summe`` lines) into the same bill model the GAEB readers
  produce; `adapter` flattens it with the GAEB flattener. Rows, row kinds, section levels and
  the column mapping are declared, so normalization does not guess them and every detector
  runs unchanged.
* **Layout rules, never guesses.** Pages without the header row are skipped and named; a page
  of the same bill whose header was drawn over keeps the previous columns. Running headers,
  footers, page and date lines and carry-overs are dropped. The quantity column's alignment and
  number format are learned from clean quantity lines, so "Breite 20 cm" in a text is not a
  quantity. A heading without quantity becomes a category when items are numbered below it;
  an item whose quantity line cannot be placed is kept and reported
  (`pdf_items_without_quantity`, needs review). Net and gross bill totals are told apart by
  their labels.
* **Provenance.** Every cell keeps its page and box (source kind `pdf_text`). PDF values carry
  no engine confidence, so a failed rule on them is downgraded to "verify in the source", as
  the issue policy already does for unscored PDF/OCR sources.
* **Checked against ground truth.** On the six PDFs with a GAEB twin, every item present in
  the PDF is found with its exact quantity (1,256 items); on the priced bid all 274 unit prices
  and totals and both bill totals match. `tests/unit/ingestion/test_pdf.py` keeps that check
  and reads all 34 sample PDFs when the dataset folder is present; self-made PDFs written by
  `tests/support/pdf_builder.py` test each rule without it.
* **Excel export.** `GET /datasets/{dataset_id}/export/xlsx` writes the extracted tables (one
  sheet per table with each row's source page or row, and an Extraction sheet) right after an
  upload, without a validation run; the run export `xlsx` adds the issues. Numbers are exact
  decimals with the source's decimals; text cells are typed as text, so formula-like content is
  shown, never evaluated; the file is byte-identical for the same input.

## Consequences

* New dependency: pypdfium2 (Apache-2.0 or BSD-3-Clause, bundles PDFium). It parses untrusted
  PDFs in process like the other parsers; uploads are still size-limited and PDFs page-limited
  (`max_pdf_pages`, default 2,000).
* Not covered: scanned PDFs (refused with a hint; OCR is a later phase), rotated pages, English
  number formats in a PDF, bills without a column header row, and text the PDF draws as
  graphics (the anonymised dataset has such lines; only OCR would read them).
* The bill model in `ingestion/gaeb/model.py` is now shared by GAEB and PDF; moving it to a
  neutral package is a rename when a third producer arrives.
