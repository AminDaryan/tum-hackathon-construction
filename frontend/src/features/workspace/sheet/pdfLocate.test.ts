import { describe, expect, it } from 'vitest';
import { findPositionItem, germanNumber, locateOnPage, positionBlock, valueItems } from './pdfLocate.ts';

/** A pdf.js text item at (x, y) in PDF points. */
function item(str: string, x: number, y: number, width = str.length * 5, height = 9) {
  return { str, transform: [height, 0, 0, height, x, y], width, height };
}

const number = (cell: object, raw: string) => ({ ...cell, raw_value: raw, data_type: 'number' });

/** A page laid out like HEM2301-2_Gesamt-LV.pdf: number at 65, text at 132, quantity at 325. */
const page = [
  item('Leistungsverzeichnis', 65, 800),
  item('05.01', 65, 780),
  item('Bereich', 120, 780),
  item('Rohrleitungen', 200, 780),
  item('05.01.45', 65, 700),
  item('Losflansch DN 100', 132, 700),
  item('1 St', 330, 670),
  item('EP..........', 377, 670),
  item('05.01.46', 65, 640),
  item('Losflansch DN 125, PN 10', 132, 640),
  item('gemäß Vorbemerkung Rohrleitungen,', 132, 628),
  item('als Zulage zu vorbeschriebener Rohrleitung.', 132, 616),
  item('1.250,50 St', 320, 600),
  item('EP..........', 377, 600),
  item('- Fortsetzung auf nächster Seite -', 130, 60),
  item('Alle Einzelbeträge Netto in EUR', 65, 40),
  item('6', 330, 30),
];

describe('germanNumber', () => {
  it('reads German prints and refuses other text', () => {
    expect(germanNumber('1.250,50')).toEqual({ units: 125050n, scale: 2 });
    expect(germanNumber('200')).toEqual({ units: 200n, scale: 0 });
    expect(germanNumber('0,5')).toEqual({ units: 5n, scale: 1 });
    expect(germanNumber('1.000')).toEqual({ units: 1000n, scale: 0 });
    expect(germanNumber('EP....')).toBeNull();
    expect(germanNumber('12.5')).toBeNull();
  });
});

describe('findPositionItem', () => {
  it('finds a number that starts a line at the left, in any notation of the same position', () => {
    expect(findPositionItem(page, '05.01.46')?.str).toBe('05.01.46');
    expect(findPositionItem(page, '5.1.46.')?.str).toBe('05.01.46');
    expect(findPositionItem(page, '05.01')?.str).toBe('05.01');
  });

  it('does not take a number that stands elsewhere on the page or is not there', () => {
    expect(findPositionItem(page, '6')).toBeNull();
    expect(findPositionItem(page, '05.01.47')).toBeNull();
    expect(findPositionItem(page, 'TEL00009')).toBeNull();
    expect(findPositionItem([], '1')).toBeNull();
  });
});

describe('positionBlock', () => {
  it('runs from the number to the next line at the same left edge, without the page foot', () => {
    // The page prints both numbers (findPositionItem above).
    const block = positionBlock(page, findPositionItem(page, '05.01.46')!).map((entry) => entry.str);
    expect(block).toEqual([
      '05.01.46',
      'Losflansch DN 125, PN 10',
      'gemäß Vorbemerkung Rohrleitungen,',
      'als Zulage zu vorbeschriebener Rohrleitung.',
      '1.250,50 St',
      'EP..........',
    ]);
    expect(positionBlock(page, findPositionItem(page, '05.01.45')!).map((entry) => entry.str)).toEqual([
      '05.01.45',
      'Losflansch DN 100',
      '1 St',
      'EP..........',
    ]);
  });
});

describe('valueItems', () => {
  // The page prints this number (findPositionItem above).
  const block = positionBlock(page, findPositionItem(page, '05.01.46')!);

  it('finds the same number as the cell, by its value, and marks only that token', () => {
    const [hit] = valueItems(block, number({}, '1250.5'));
    expect(hit.str).toBe('1.250,50 St');
    expect(hit.left).toBe(320);
    expect(hit.right).toBe(360);
    expect(valueItems(block, { raw_value: '1250.50', normalized_value: { kind: 'number', value: '1250.50' } })).toHaveLength(1);
    expect(valueItems(block, number({}, '1250'))).toEqual([]);
  });

  it('finds a unit as a whole word and the lines of a longer text', () => {
    const [unit] = valueItems(block, { raw_value: 'st' });
    expect(unit.left).toBe(365);
    expect(valueItems(block, { raw_value: 'm' })).toEqual([]);
    const lines = valueItems(block, {
      raw_value: 'Losflansch DN 125, PN 10\ngemäß Vorbemerkung Rohrleitungen, sonst wie vor, als Zulage zu vorbeschriebener Rohrleitung.',
    });
    expect(lines.map((entry) => entry.str)).toEqual([
      'Losflansch DN 125, PN 10',
      'gemäß Vorbemerkung Rohrleitungen,',
      'als Zulage zu vorbeschriebener Rohrleitung.',
    ]);
  });

  it('finds nothing for an empty cell or a value that is not printed', () => {
    expect(valueItems(block, null)).toEqual([]);
    expect(valueItems(block, { raw_value: '  ' })).toEqual([]);
    expect(valueItems(block, number({}, '63.10'))).toEqual([]);
  });
});

describe('locateOnPage', () => {
  it('gives the position box and the value box in PDF points', () => {
    const found = locateOnPage(page, { oz: '05.01.46', cell: number({}, '1250.5') });
    expect(found?.valueFound).toBe(true);
    expect(found?.position).toEqual({ left: 63, right: 377 + 12 * 5 + 2, top: 640 + 9 + 2, bottom: 600 - 2.7 - 2 });
    expect(found?.value).toEqual({ left: 318, right: 362, top: 611, bottom: 600 - 2.7 - 2 });
  });

  it('marks the number itself for the position number cell', () => {
    const found = locateOnPage(page, { oz: '05.01.46', cell: { raw_value: '05.01.46' }, isOz: true });
    expect(found?.value).toEqual({ left: 63, right: 65 + 40 + 2, top: 651, bottom: 640 - 2.7 - 2 });
  });

  it('marks only the position when the value is not printed, and nothing for another page', () => {
    const found = locateOnPage(page, { oz: '05.01.46', cell: number({}, '63.10') });
    expect(found?.valueFound).toBe(false);
    expect(found?.value).toBeNull();
    expect(found?.position).not.toBeNull();
    expect(locateOnPage(page, { oz: '07.01.1', cell: null })).toBeNull();
  });
});
