/**
 * Display formatting in the UI language (see i18n): grouping, decimal separators, dates and
 * units follow it. The functions never invent precision: decimals arrive from the API as strings
 * and are formatted without converting them to binary floating point.
 */
import { intlLocale, t } from '../i18n/messages.ts';

const EMPTY = '—';
const DECIMAL_PATTERN = /^[-+]?\d+(\.\d+)?$/;
const MAX_FRACTION_DIGITS = 20;

const formats = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat>();

/** A cached Intl.NumberFormat for the current language. */
function numberFormat(options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `n${intlLocale()}${JSON.stringify(options)}`;
  if (!formats.has(key)) formats.set(key, new Intl.NumberFormat(intlLocale(), options));
  return formats.get(key) as Intl.NumberFormat;
}

/** A cached Intl.DateTimeFormat for the current language. */
function dateFormat(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `d${intlLocale()}${JSON.stringify(options)}`;
  if (!formats.has(key)) formats.set(key, new Intl.DateTimeFormat(intlLocale(), options));
  return formats.get(key) as Intl.DateTimeFormat;
}

/** Number.isFinite that TypeScript reads as a check of the type. */
function isFiniteNumber(value: unknown): value is number {
  return Number.isFinite(value);
}

/** A number with exactly `digits` fraction digits: (1.25, 1) -> "1.3", in German "1,3". */
function fixed(value: number, digits: number): string {
  return numberFormat({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

/**
 * Formats a count with grouping separators: 12345 -> "12,345".
 */
export function formatCount(value: number | null | undefined): string {
  return isFiniteNumber(value) ? numberFormat({ maximumFractionDigits: 0 }).format(value) : EMPTY;
}

/**
 * Formats a decimal string exactly ("1250.5" -> "1,250.5", in German "1.250,5"), keeping the
 * number of fraction digits the backend sent. Intl formats the string itself, not a float, so
 * every digit stays. Values that are not plain decimals are returned verbatim.
 *
 * @param options `signed` prefixes positive values with "+"
 */
export function formatDecimal(
  value: string | number | null | undefined,
  { signed = false }: { signed?: boolean } = {},
): string {
  if (value === null || value === undefined || value === '') {
    return EMPTY;
  }
  const text = String(value).trim();
  if (!DECIMAL_PATTERN.test(text)) {
    return text;
  }
  const fractionDigits = text.includes('.') ? text.split('.')[1].length : 0;
  if (fractionDigits > MAX_FRACTION_DIGITS) {
    return text;
  }
  return numberFormat({
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
    signDisplay: signed ? 'exceptZero' : 'auto',
  }).format(text as Intl.StringNumericLiteral);
}

/**
 * Formats an amount of money exactly, with at least two fraction digits and its currency when
 * known: ("9938.4", "EUR") -> "9,938.40 EUR". The digits are padded as text, never rounded.
 */
export function formatMoney(value: string | null | undefined, currency?: string | null): string {
  const text = value?.trim() ?? '';
  const [whole, fraction = ''] = text.split('.');
  const number = formatDecimal(DECIMAL_PATTERN.test(text) ? `${whole}.${fraction.padEnd(2, '0')}` : value);
  return currency && number !== EMPTY ? `${number} ${currency}` : number;
}

/**
 * Formats an ISO 8601 timestamp in the UI language, e.g. "Nov 17, 2026, 8:00 PM" or
 * "17.11.2026, 20:00".
 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return EMPTY;
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso) : dateFormat({ dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

/** Formats the day of an ISO 8601 timestamp in the UI language: "Nov 22, 2026" or "22.11.2026". */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) {
    return EMPTY;
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso) : dateFormat({ dateStyle: 'medium' }).format(date);
}

/** File size with binary units: 48211 -> "47.1 KB". */
export function formatBytes(bytes: number | null | undefined): string {
  if (!isFiniteNumber(bytes) || bytes < 0) {
    return EMPTY;
  }
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${fixed(value, 1)} ${units[unit]}`;
}

/** A raw score or ratio with fixed decimals: 0.857 -> "0.86". Never rendered as a percentage. */
export function formatScore(value: number | null | undefined, digits = 2): string {
  return isFiniteNumber(value) ? fixed(value, digits) : EMPTY;
}

/**
 * "1 issue" / "12 issues" with a formatted count; the word is translated, so pass English
 * forms that are catalogue entries (English and German both pick the singular only for 1).
 */
export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${formatCount(count)} ${t(count === 1 ? singular : plural)}`;
}
