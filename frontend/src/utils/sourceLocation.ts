/**
 * Formatting of canonical SourceLocation objects (see backend/app/models/source.py).
 */
import { t } from '../i18n/messages.ts';
import type { SourceLocation } from '../services/apiTypes.ts';
import { a1Reference } from './a1.ts';

/**
 * Quotes a sheet name the way Excel does when it is not a plain identifier: `'Bill 1'`.
 */
function quoteSheetName(name: string): string {
  if (/^[A-Za-z0-9_.]+$/.test(name)) {
    return name;
  }
  return `'${name.replaceAll("'", "''")}'`;
}

/**
 * Compact cell reference: `LV!C12` for spreadsheets, `record 14, field 3` for delimited text,
 * `row 12, column 4, XML line 345` for a GAEB bill (row and column of the table the bill is
 * shown as, and the line in the XML file), `row 12, column 4, line 345` for a GAEB 90 bill,
 * `Table 2, row 5, column 3` for a Word table, `paragraph 31` for a bill written as Word
 * paragraphs, `page 2` for PDF/OCR sources.
 *
 * @returns null when the location is unknown
 */
export function formatCellReference(source: SourceLocation | null | undefined): string | null {
  if (!source) {
    return null;
  }
  if (source.kind === 'spreadsheet') {
    const a1 = source.a1 ?? a1Reference(source.row_number, source.column_number);
    const sheet = source.sheet_name ? quoteSheetName(source.sheet_name) : null;
    if (sheet && a1) return `${sheet}!${a1}`;
    return a1 ?? sheet;
  }
  if (source.kind === 'delimited_text') {
    const parts: string[] = [];
    if (source.row_number) parts.push(t('record {number}', { number: source.row_number }));
    if (source.column_number) parts.push(t('field {number}', { number: source.column_number }));
    return parts.length ? parts.join(', ') : null;
  }
  if (source.kind === 'gaeb_xml' || source.kind === 'gaeb_90') {
    const parts: string[] = [];
    if (source.row_number) parts.push(t('row {number}', { number: source.row_number }));
    if (source.column_number) parts.push(t('column {number}', { number: source.column_number }));
    if (source.line_number) {
      const number = source.line_number;
      parts.push(source.kind === 'gaeb_xml' ? t('XML line {number}', { number }) : t('line {number}', { number }));
    }
    return parts.length ? parts.join(', ') : null;
  }
  if (source.kind === 'word') {
    if (source.line_number) return t('paragraph {number}', { number: source.line_number });
    const parts: string[] = [];
    if (source.sheet_name) parts.push(source.sheet_name);
    if (source.row_number) parts.push(t('row {number}', { number: source.row_number }));
    if (source.column_number) parts.push(t('column {number}', { number: source.column_number }));
    return parts.length ? parts.join(', ') : null;
  }
  return source.page_number ? t('page {number}', { number: source.page_number }) : null;
}

/**
 * Long description used in tooltips, mirroring SourceLocation.describe() in the backend:
 * `Sheet 'LV' cell C12`, `CSV record 14, field 3`, `GAEB row 12, column 4, XML line 345`,
 * `GAEB 90 row 12, column 4, line 345`, `Word Table 2, row 5, column 3`, `Word paragraph 31`,
 * `pdf_text page 2`.
 */
export function describeSource(source: SourceLocation | null | undefined): string | null {
  if (!source) {
    return null;
  }
  if (source.kind === 'spreadsheet') {
    const sheet = source.sheet_name;
    const cell = source.a1 ?? a1Reference(source.row_number, source.column_number);
    if (sheet) return cell ? t("Sheet '{sheet}' cell {cell}", { sheet, cell }) : t("Sheet '{sheet}'", { sheet });
    return cell ? t('Sheet cell {cell}', { cell }) : t('Sheet');
  }
  if (source.kind === 'delimited_text') {
    const reference = formatCellReference(source);
    return reference ? `CSV ${reference}` : 'CSV';
  }
  if (source.kind === 'gaeb_xml') {
    const reference = formatCellReference(source);
    return reference ? `GAEB ${reference}` : 'GAEB';
  }
  if (source.kind === 'gaeb_90') {
    const reference = formatCellReference(source);
    return reference ? `GAEB 90 ${reference}` : 'GAEB 90';
  }
  if (source.kind === 'word') {
    const reference = formatCellReference(source);
    return reference ? `Word ${reference}` : 'Word';
  }
  const kind = source.kind;
  return source.page_number ? t('{kind} page {number}', { kind, number: source.page_number }) : t('{kind} page unknown', { kind });
}
