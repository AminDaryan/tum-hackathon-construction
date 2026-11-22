# 0014: Word documents: tables as tables, item paragraphs as a bill

Status: accepted (2026-11-21). Adds a format next to [0011](0011-pdf-bills-and-excel-export.md)
(PDF) and [0012](0012-ocr-for-scanned-pdfs.md) (scans).

## Context

Bills of quantities, and extracts of them, arrive as Word documents. The workbench rejected
them, so a reviewer had to retype them or print them to PDF. The sample dataset has one:
`LV-Positionen.docx`, 40 items written as paragraphs (`2.3.10 – Straßendecke schneiden [m]`)
under group names, with no quantities or prices. Bills written in Word are usually a table
(Pos., Kurztext, Menge, Einheit, EP, GP), sometimes several tables with headings between
them.

## Decision

* **Format.** `.docx` (Office Open XML) only. A legacy `.doc` is refused with the advice to
  save it as `.docx` or PDF: reading the binary format would need LibreOffice or a converter in
  the image. The upload check treats a `.docx` like an XLSX: extension and content must agree
  (a ZIP with `[Content_Types].xml` and `word/document.xml`), the central directory is checked
  for ZIP bombs, encryption and unsafe names, and a macro project is reported and ignored. A
  password-protected document (an OLE container) is named as such.
* **What is read.** Only `word/document.xml`, plus `styles.xml` (which styles are headings) and
  `numbering.xml` (which paragraphs Word numbers itself). The XML is parsed with lxml without
  DTDs, entity expansion or network access, and a DOCTYPE is refused. No library beyond lxml
  was added. Text is taken as Word shows it: runs in hyperlinks, content controls and fields
  (their result), tracked insertions; tracked deletions and field codes are left out.
* **Tables become tables.** Each table of the document becomes a table named after its place
  (`Table 2`), with Word's rows and columns, so a finding points to a row a reader finds in
  Word (`Word Table 2, row 5, column 3`). Merged cells (`gridSpan`, `vMerge`) become merged
  ranges with the text in the first cell. Cell text is kept as written. Normalization then
  finds the header, maps the columns and parses the numbers exactly as for a spreadsheet; the
  adapter assumes nothing about bills. A table inside a cell is read as that cell's text and
  reported.
* **Item paragraphs become a bill.** Paragraphs that start with an item number (at least two
  numeric parts, `1.10`, `01.02.0030`) and give a unit, in brackets at the end or in a
  tab-separated column, are read into the bill model that GAEB and PDF bills share. Numbers in
  tab-separated columns (German notation) are the quantity, unit price and line total. The
  table is flattened like a GAEB bill, so its rows and columns are declared, and every cell
  carries its paragraph number (`Word paragraph 31`). Headings are:
  * Word heading styles;
  * numbered paragraphs whose number begins later item numbers (`2.3 Asphalt`, `01 Erdarbeiten`),
    nested by number;
  * short lines before an item or after an empty line (`Asphalt`).

  The rest becomes either long text of the item before or a note row (`oder`, `mit`, `…`).
  A document needs at least three such items to count as a bill, so numbered contract text
  (`1.1 Geltungsbereich`) is not read as one.
* **What is not read is said.** These each get a warning:
  * numbers that Word adds to numbered paragraphs, which are not stored in the text;
  * text boxes;
  * content imported from other files (`altChunk`);
  * nested tables.

  Inferring the structure of an item list is reported too, so the reviewer checks it in the
  table preview. A document with neither a table nor an item list is refused with a message
  that describes both forms.

## Not adopted

* **python-docx or docx2python.** They would add a dependency for what about 300 lines of lxml
  do. They also hide the details the reader needs: merged cells as Word stores them, tracked
  changes and field codes.
* **Rendering Word's automatic numbering** (`numbering.xml` counters and level texts). Word's
  rules for continuing and restarting lists are intricate, and a wrong number on an item
  would be worse than none. Such paragraphs are reported instead.
* **Joining tables across headings into one table.** Locations would no longer name a row of a
  Word table, and the headings between them are not reliably sections. Each table stays its
  own table.

## Consequences

* A finding on a Word value points to the table, row and column, or to the paragraph.
* The structure of an item list is inferred. A short long-text line directly before the next
  item can be read as a group heading, and the warning says to check.
* Word documents with only images (scanned pages pasted into Word) give no table; they should
  be uploaded as PDF, which is read by OCR.
