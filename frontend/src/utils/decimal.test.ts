import { describe, expect, it } from 'vitest';
import {
  absDecimal,
  compareDecimal,
  decimalToString,
  multiplyDecimal,
  parseDecimal,
  percentChange,
  roundDecimal,
  subtractDecimal,
  type Decimal,
} from './decimal.ts';

// The cases that read as null only go to toBeNull, never into the arithmetic.
const d = (text: unknown) => parseDecimal(text) as Decimal;
const s = (value: Decimal) => decimalToString(value);

describe('decimal', () => {
  it('reads plain decimals, a comma when there is no point, and refuses everything else', () => {
    expect(s(d('1250.5'))).toBe('1250.5');
    expect(s(d('-0.90'))).toBe('-0.90');
    expect(s(d('63,5'))).toBe('63.5');
    expect(s(d(12.25))).toBe('12.25');
    expect(d('1.234,5')).toBeNull();
    expect(d('1e3')).toBeNull();
    expect(d('abc')).toBeNull();
    expect(d(null)).toBeNull();
    expect(d(Number.NaN)).toBeNull();
  });

  it('adds, subtracts, multiplies and compares without binary floating point', () => {
    expect(s(subtractDecimal(d('500.00'), d('520.00')))).toBe('-20.00');
    expect(s(multiplyDecimal(d('12.5'), d('40.00')))).toBe('500.000');
    expect(compareDecimal(d('10'), d('9.99'))).toBe(1);
    expect(compareDecimal(d('1.50'), d('1.5'))).toBe(0);
    expect(s(absDecimal(d('-3.2')))).toBe('3.2');
  });

  it('rounds half away from zero to the given places', () => {
    expect(s(roundDecimal(d('2.345')))).toBe('2.35');
    expect(s(roundDecimal(d('-2.345')))).toBe('-2.35');
    expect(s(roundDecimal(d('2.344')))).toBe('2.34');
    expect(s(roundDecimal(d('7'), 2))).toBe('7.00');
    expect(s(roundDecimal(d('-0.004')))).toBe('0.00');
  });

  it('gives the change in percent, or null from zero', () => {
    expect(percentChange(d('520.00'), d('500.00'), 2)).toBe('-3.85');
    expect(percentChange(d('578.29'), d('10'), 1)).toBe('-98.3');
    expect(percentChange(d('0'), d('5'))).toBeNull();
  });
});
