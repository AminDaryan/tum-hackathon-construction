/**
 * Exact decimal arithmetic on plain decimal strings ("1250.5", "-0.90"), for money shown or
 * saved by the workspace. Values are scaled BigInts, so no binary floating point is involved.
 * Only what the pricing and the money ordering need: parse, compare, add, subtract, multiply,
 * round half away from zero, and a percentage change.
 */

const PATTERN = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;

/** value = units / 10^scale */
export interface Decimal {
  units: bigint;
  scale: number;
}

/**
 * Reads a plain decimal string or a finite number. A comma is accepted as the decimal separator
 * when the text has no point ("63,5"), so a German entry works in the price field.
 *
 * @returns null when the value is not a plain decimal
 */
export function parseDecimal(value: unknown): Decimal | null {
  if (value === null || value === undefined) return null;
  let text = typeof value === 'number' ? (Number.isFinite(value) ? String(value) : '') : String(value).trim();
  if (!text.includes('.') && /^[+-]?\d+,\d+$/.test(text)) text = text.replace(',', '.');
  if (!PATTERN.test(text) || /e/i.test(text)) return null;
  const negative = text.startsWith('-');
  const unsigned = text.replace(/^[+-]/, '');
  const [whole, fraction = ''] = unsigned.split('.');
  const units = BigInt(`${whole || '0'}${fraction}`);
  return { units: negative ? -units : units, scale: fraction.length };
}

function rescale(decimal: Decimal, scale: number): bigint {
  return decimal.units * 10n ** BigInt(scale - decimal.scale);
}

function align(a: Decimal, b: Decimal): [bigint, bigint, number] {
  const scale = Math.max(a.scale, b.scale);
  return [rescale(a, scale), rescale(b, scale), scale];
}

/** @returns -1, 0 or 1 */
export function compareDecimal(a: Decimal, b: Decimal): -1 | 0 | 1 {
  const [x, y] = align(a, b);
  return x < y ? -1 : x > y ? 1 : 0;
}

export function subtractDecimal(a: Decimal, b: Decimal): Decimal {
  const [x, y, scale] = align(a, b);
  return { units: x - y, scale };
}

export function multiplyDecimal(a: Decimal, b: Decimal): Decimal {
  return { units: a.units * b.units, scale: a.scale + b.scale };
}

export function absDecimal(a: Decimal): Decimal {
  return { units: a.units < 0n ? -a.units : a.units, scale: a.scale };
}

/** Rounds half away from zero to `places` fraction digits (the commercial rule for cents). */
export function roundDecimal(a: Decimal, places = 2): Decimal {
  if (a.scale <= places) return { units: rescale(a, places), scale: places };
  const divisor = 10n ** BigInt(a.scale - places);
  const negative = a.units < 0n;
  const magnitude = negative ? -a.units : a.units;
  let quotient = magnitude / divisor;
  if ((magnitude % divisor) * 2n >= divisor) quotient += 1n;
  return { units: negative ? -quotient : quotient, scale: places };
}

/** @returns e.g. "1250.50", "-0.9"; keeps the scale */
export function decimalToString(a: Decimal): string {
  const negative = a.units < 0n;
  const digits = (negative ? -a.units : a.units).toString().padStart(a.scale + 1, '0');
  const whole = a.scale ? digits.slice(0, -a.scale) : digits;
  const fraction = a.scale ? `.${digits.slice(-a.scale)}` : '';
  const text = `${whole}${fraction}`;
  return negative && /[1-9]/.test(text) ? `-${text}` : text;
}

function isZero(a: Decimal): boolean {
  return a.units === 0n;
}

/**
 * The change from `from` to `to` in percent, rounded to `places`, as a decimal string; null when
 * `from` is zero.
 */
export function percentChange(from: Decimal, to: Decimal, places = 1): string | null {
  if (isZero(from)) return null;
  const difference = subtractDecimal(to, from);
  // difference / from * 100, computed on integers with extra digits, then rounded.
  const extra = places + 2;
  const [d, f] = align(difference, from);
  const scaled = (d * 100n * 10n ** BigInt(extra)) / f;
  return decimalToString(roundDecimal({ units: scaled, scale: extra }, places));
}
