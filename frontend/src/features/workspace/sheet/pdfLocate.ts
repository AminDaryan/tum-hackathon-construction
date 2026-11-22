/**
 * Finding a sheet cell in the printed bill (the PDF) by what the PDF says, not by a guess.
 *
 * A position is found by its number (OZ) standing first on a line at the left of the page,
 * compared in its normalized form ("03.01.0001" and "3.1.1" are the same position). Its block
 * runs down to the next line that starts at the same left edge (the next position, a heading
 * or the page footer). Inside the block the cell's value is looked for exactly: the same
 * number (German "1.250,50" or plain), the same unit, or lines of the cell's text. When the
 * value is not printed there (an empty price in a blank bill), only the position is marked.
 * Boxes are in PDF points with a bottom-left origin, like pdf.js text items.
 */
import { compareDecimal, parseDecimal, type Decimal } from '../../../utils/decimal.ts';
import type { PdfBox, PdfTextItem } from './pdfBoxes.ts';

/** Items within this many points of each other's baseline stand on one line. */
const LINE_TOLERANCE = 2.5;
/** A line starts "at the left edge" of a position when it starts within this many points of it. */
const EDGE_TOLERANCE = 3;
/** A position number stands within this many points of the leftmost number that starts a line. */
const MARGIN_TOLERANCE = 30;
/** Lines a printed bill puts at the foot of a page that a position continues past. */
const PAGE_FOOTER = /^(-\s*)?(Fortsetzung|Übertrag)\b/i;
/** Text lines shorter than this are not matched inside a longer cell text. */
const MIN_TEXT_PART = 4;

/** A pdf.js text item that prints something. */
export type Word = PdfTextItem & { str: string };
/** A word, or the part of one (`left` to `right`) that holds a matching token. */
type WordPart = Word & { left?: number; right?: number };

function ozParts(text: string | number) {
  return String(text)
    .trim()
    .replace(/\.+$/, '')
    .split(/\s*\.\s*/);
}

/**
 * The comparable form of a position number: levels without leading zeros, no trailing dot.
 *
 * @param text an OZ as written in the bill, e.g. "03.01.0001."
 * @returns e.g. "3.1.1"; null when the text is not a position number
 */
function normalizeOz(text: unknown): string | null {
  if (typeof text !== 'string' && typeof text !== 'number') return null;
  const parts = ozParts(text);
  if (!parts.every((part) => /^\d+$/.test(part))) return null;
  return parts.map((part) => String(Number(part))).join('.');
}

/** The text items of a page that print something (pdf.js also gives marked-content items). */
export function words(items: readonly object[] | null | undefined): Word[] {
  return (items ?? []).filter(
    (item): item is Word =>
      'str' in item && typeof item.str === 'string' && item.str.trim() !== '' && 'transform' in item && Array.isArray(item.transform),
  );
}

const x = (item: Word) => item.transform[4];
const y = (item: Word) => item.transform[5];
const fontHeight = (item: Word) => (item.height > 0 ? item.height : 9);

/** The box around text items, a little larger than the glyphs. */
export function boxOf(items: WordPart[]): PdfBox | null {
  if (!items.length) return null;
  return {
    left: Math.min(...items.map((item) => item.left ?? x(item))) - 2,
    right: Math.max(...items.map((item) => item.right ?? x(item) + item.width)) + 2,
    top: Math.max(...items.map((item) => y(item) + fontHeight(item))) + 2,
    bottom: Math.min(...items.map((item) => y(item) - fontHeight(item) * 0.3)) - 2,
  };
}

/** Whether no other item on the same line starts left of this one. */
function firstOnLine(item: Word, all: Word[]) {
  return !all.some((other) => other !== item && Math.abs(y(other) - y(item)) <= LINE_TOLERANCE && x(other) < x(item) - 0.5);
}

/**
 * The item that prints this position's number at the start of a line, on one page.
 *
 * @param oz the position number as the bill writes it
 * @returns the text item, or null when the page does not start a line with it
 */
export function findPositionItem(items: readonly object[], oz: string | null | undefined): Word | null {
  const wanted = normalizeOz(oz);
  if (!wanted) return null;
  const all = words(items);
  const numbers = all.filter((item) => normalizeOz(item.str.trim()) && firstOnLine(item, all));
  if (!numbers.length) return null;
  const margin = Math.min(...numbers.map(x)) + MARGIN_TOLERANCE;
  return numbers.find((item) => x(item) <= margin && normalizeOz(item.str.trim()) === wanted) ?? null;
}

/**
 * The text items of a position: from its number's line down to the next line that starts at
 * the same left edge, or the end of the page.
 */
export function positionBlock(items: readonly object[], ozItem: Word): Word[] {
  const all = words(items);
  const top = y(ozItem) + LINE_TOLERANCE;
  const next = all
    .filter((item) => y(item) < y(ozItem) - LINE_TOLERANCE && Math.abs(x(item) - x(ozItem)) <= EDGE_TOLERANCE && firstOnLine(item, all))
    .reduce<Word | null>((highest, item) => (!highest || y(item) > y(highest) ? item : highest), null);
  const bottom = next ? y(next) + LINE_TOLERANCE : -Infinity;
  return all.filter((item) => y(item) <= top && y(item) > bottom && !PAGE_FOOTER.test(item.str.trim()));
}

/** A number as a German print writes it ("1.250,50", "200", "0,5"); null for anything else. */
export function germanNumber(text: string): Decimal | null {
  const value = String(text).trim();
  if (!/^-?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$/.test(value)) return null;
  return parseDecimal(value.replace(/\./g, '').replace(',', '.'));
}

/** The part of an item that holds one of its space-separated tokens, by the share of characters. */
function tokenPart(item: Word, start: number, length: number): WordPart {
  const size = item.str.length || 1;
  return {
    ...item,
    left: x(item) + (item.width * start) / size,
    right: x(item) + (item.width * (start + length)) / size,
  };
}

function tokensOf(item: Word) {
  const found: { text: string; start: number }[] = [];
  const pattern = /\S+/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(item.str)) !== null) found.push({ text: match[0], start: match.index });
  return found;
}

const squash = (text: string) => String(text).replace(/\s+/g, ' ').trim().toLowerCase();

/** What the search reads of a cell. */
type ValueCell = { raw_value?: string | null; normalized_value?: object | null; data_type?: string };

/** The number a cell holds: the reader's settled number, else its text read as a number. */
function cellNumber(cell: ValueCell | null | undefined): Decimal | null {
  const normalized = cell?.normalized_value as { kind?: string; value?: unknown } | null | undefined;
  if (normalized && normalized.kind === 'number' && normalized.value != null) return parseDecimal(String(normalized.value));
  const raw = typeof cell?.raw_value === 'string' ? cell.raw_value.trim() : '';
  return raw ? (parseDecimal(raw) ?? germanNumber(raw)) : null;
}

/**
 * The items (or parts of items) inside a position's block that print the cell's value.
 *
 * @param block text items of the position
 * @returns items with `left` and `right` set where only a token of the item matches
 */
export function valueItems(block: Word[], cell: ValueCell | null | undefined): WordPart[] {
  const raw = typeof cell?.raw_value === 'string' ? cell.raw_value.trim() : '';
  if (!raw) return [];
  const number = cell?.data_type === 'number' || /^[\d.,\s-]+$/.test(raw) ? cellNumber(cell) : null;
  if (number) {
    const hits: WordPart[] = [];
    for (const item of block) {
      for (const token of tokensOf(item)) {
        const printed = germanNumber(token.text) ?? parseDecimal(token.text);
        if (printed && compareDecimal(printed, number) === 0) hits.push(tokenPart(item, token.start, token.text.length));
      }
    }
    return hits.slice(0, 1);
  }
  const text = squash(raw);
  if (!text.includes(' ')) {
    for (const item of block) {
      const token = tokensOf(item).find((candidate) => candidate.text.toLowerCase() === text);
      if (token) return [tokenPart(item, token.start, token.text.length)];
    }
    return [];
  }
  // A longer text: every line of the block that is part of it (the short text, the long text).
  return block.filter((item) => {
    const line = squash(item.str);
    return line.length >= MIN_TEXT_PART && !normalizeOz(line) && (text.includes(line) || line.includes(text));
  });
}

/**
 * Where a cell of a bill row stands on one PDF page.
 *
 * @param items the page's text items (`page.getTextContent().items`)
 * @param target the row's position
 *   number, the cell, and whether the cell is the position number itself
 * @returns boxes in PDF
 *   points; null when the page does not hold the position
 */
export function locateOnPage(
  items: readonly object[],
  { oz, cell = null, isOz = false }: { oz: string | null | undefined; cell?: ValueCell | null; isOz?: boolean },
): { position: PdfBox | null; value: PdfBox | null; valueFound: boolean } | null {
  const ozItem = findPositionItem(items, oz);
  if (!ozItem) return null;
  const block = positionBlock(items, ozItem);
  const hits = isOz ? [ozItem] : valueItems(block, cell);
  return { position: boxOf(block), value: hits.length ? boxOf(hits) : null, valueFound: hits.length > 0 };
}
