# 0012: Text recognition (OCR) for scanned PDF bills

Status: accepted. Extends [0011](0011-pdf-bills-and-excel-export.md).

## Context

ADR 0011 reads printed bills from a PDF's text layer and refuses scans. Bills still arrive as
scans (signed bids, faxed or photocopied tenders), and some PDFs have a text layer that cannot
be decoded (fonts without a Unicode mapping). Such pages need text recognition. The workbench
runs locally, so the engine has to run on the reviewer's machine.

## Decision

* **Engine: Tesseract** (Apache-2.0), the `tesseract` command with German and English language
  data, installed in the Docker image (`tesseract-ocr`, `-deu`, `-eng`). It reports each word
  with its box and a confidence, which is what the bill reader needs. Heavier engines (deep
  learning models in Python) were not needed: the measured accuracy below is reached with
  Tesseract and the safeguards that follow.
* **Which pages.** Only pages without a usable text layer: none at all, or more than 30 %
  unreadable characters (replacement or private-use characters). Text-layer pages keep their
  exact text.
* **Reading a page** (`ingestion/pdf/ocr.py`). A quick reading at 150 dpi measures the skew
  (median slope of Tesseract's text lines); the page is then rendered by PDFium rotated straight
  and read at 300 dpi (page segmentation mode 4, which keeps quantity lines with dotted leaders).
  Images are written as PGM, so no imaging library is needed; the `tesseract` processes run in
  parallel (one per core, at most 8), rendering stays in one thread (PDFium is not
  thread-safe).
* **Superscripts.** Tesseract has no `²`/`³` (`m³` comes out as `m?`, `m’`, `Mo`). The glyph is
  cropped three ways, enlarged and read as a single character limited to `2`/`3`; the reads vote
  and only a clear winner is used. A unit read with a full-size digit (`m2`) is never read again:
  that once turned `m3` into `m²`.
* **Never a wrong value silently.** On recognised pages: an amount column holding a broken
  number (`2.035,` next to `930`) gets no value; an item block with two quantity lines (an item
  number was not recognised) gets no quantity; a unit that cannot be read is kept as read
  (`m?`) so the unit check reports it. Values carry Tesseract's confidence into
  `extraction_confidence`; a failed rule on them is downgraded to "verify in the source".
  Every recognised document gets the warning `pdf_ocr_used` (needs review) with the pages, the
  skew straightened, the superscripts read again and the values below 80 % confidence.
* **Settings** `TWB_OCR__*`: `ENABLED`, `COMMAND`, `LANGUAGES` (`deu+eng`), `DPI` (300),
  `PAGE_SEGMENTATION` (4), `MAX_PAGES` (300), `WORKERS` (0 = per core), `PAGE_TIMEOUT_SECONDS`.
  `GET /health` reports whether OCR is available and why not. Without it, a scan is refused as
  a PDF whose text could not be read (the reason goes to the server log), and scanned pages of a
  mixed PDF are named (`pdf_ocr_unavailable`).

## Measured

The sample dataset's PDFs were turned into image-only scans (PDFium renders each page and
places the image, straight or rotated) and read back; their GAEB twins give every value.

| Scan (300 dpi) | Items | Quantities exact | Prices exact | Wrong values |
| --- | --- | --- | --- | --- |
| Priced bid, straight | 274/274 | 274 | 274 | 0 |
| Priced bid, skewed 1.2° | 274/274 | 274 | 274 | 0 |
| LV-Ausdruck, straight / 1.2° | 50/50 | 48 / 45 | blank form | 0 |
| Abgabe (monospace), straight | 247/247 | 247 | 237 | 0 |
| Abgabe (monospace), skewed 1.2° | 205/247 | 177 | 172 | 0 |

What is not read is reported (missing quantity, unknown unit, missing price), not guessed. A
91-page scan takes about 1.5 minutes with 8 processes.

## Consequences

* The image grows by Tesseract and its data (about 40 MB). Running the backend outside Docker
  needs `tesseract` with `deu` and `eng` installed for OCR; without it, text PDFs still work.
* Uploads of scans are slower (about 1 second per page); the upload waits for the extraction.
* Not covered: handwriting, rotated pages (90°), photos with perspective, columns that the
  scan cuts off, and number formats other than German. The tests that run Tesseract are
  skipped where it is not installed (they run in the Docker image).
