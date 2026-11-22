import { describe, expect, it } from 'vitest';
import { firstSentence, readingNote } from './cellText.ts';
import { cellAddress, cellKey, isEditKey, moveCell, PAGE_STEP, printableKey, sortColumns, stepAcross } from './sheetMoves.ts';

const SIZE = { rowCount: 30, columnCount: 5 };

describe('moveCell', () => {
  it('moves one cell with the arrow keys and stops at the edges', () => {
    const middle = { row: 3, column: 2 };
    expect(moveCell(middle, 'ArrowUp', SIZE)).toEqual({ row: 2, column: 2 });
    expect(moveCell(middle, 'ArrowDown', SIZE)).toEqual({ row: 4, column: 2 });
    expect(moveCell(middle, 'ArrowLeft', SIZE)).toEqual({ row: 3, column: 1 });
    expect(moveCell(middle, 'ArrowRight', SIZE)).toEqual({ row: 3, column: 3 });

    expect(moveCell({ row: 0, column: 0 }, 'ArrowUp', SIZE)).toEqual({ row: 0, column: 0 });
    expect(moveCell({ row: 0, column: 0 }, 'ArrowLeft', SIZE)).toEqual({ row: 0, column: 0 });
    expect(moveCell({ row: 29, column: 4 }, 'ArrowDown', SIZE)).toEqual({ row: 29, column: 4 });
    expect(moveCell({ row: 29, column: 4 }, 'ArrowRight', SIZE)).toEqual({ row: 29, column: 4 });
  });

  it('jumps to the first and last cell of the row, or of the page with Ctrl', () => {
    const middle = { row: 3, column: 2 };
    expect(moveCell(middle, 'Home', SIZE)).toEqual({ row: 3, column: 0 });
    expect(moveCell(middle, 'End', SIZE)).toEqual({ row: 3, column: 4 });
    expect(moveCell(middle, 'Home', { ...SIZE, ctrlKey: true })).toEqual({ row: 0, column: 0 });
    expect(moveCell(middle, 'End', { ...SIZE, ctrlKey: true })).toEqual({ row: 29, column: 4 });
  });

  it('moves by a block of rows with Page Up and Page Down', () => {
    expect(moveCell({ row: 3, column: 1 }, 'PageDown', SIZE)).toEqual({ row: 3 + PAGE_STEP, column: 1 });
    expect(moveCell({ row: 3, column: 1 }, 'PageUp', SIZE)).toEqual({ row: 0, column: 1 });
    expect(moveCell({ row: 25, column: 1 }, 'PageDown', SIZE)).toEqual({ row: 29, column: 1 });
  });

  it('ignores other keys, a missing position and an empty page', () => {
    expect(moveCell({ row: 1, column: 1 }, 'a', SIZE)).toBeNull();
    expect(moveCell({ row: 1, column: 1 }, 'Enter', SIZE)).toBeNull();
    expect(moveCell(null, 'ArrowDown', SIZE)).toBeNull();
    expect(moveCell({ row: 0, column: 0 }, 'ArrowDown', { rowCount: 0, columnCount: 5 })).toBeNull();
  });

  it('clamps a position that lies outside a smaller page', () => {
    expect(moveCell({ row: 80, column: 9 }, 'ArrowUp', SIZE)).toEqual({ row: 28, column: 4 });
  });
});

describe('stepAcross', () => {
  it('moves right or left on the same row and stays inside it', () => {
    expect(stepAcross({ row: 2, column: 1 }, 'right', 5)).toEqual({ row: 2, column: 2 });
    expect(stepAcross({ row: 2, column: 1 }, 'left', 5)).toEqual({ row: 2, column: 0 });
    expect(stepAcross({ row: 2, column: 4 }, 'right', 5)).toEqual({ row: 2, column: 4 });
    expect(stepAcross({ row: 2, column: 0 }, 'left', 5)).toEqual({ row: 2, column: 0 });
  });
});

describe('editing keys', () => {
  it('starts editing with Enter and F2, not with modifiers', () => {
    expect(isEditKey({ key: 'Enter' })).toBe(true);
    expect(isEditKey({ key: 'F2' })).toBe(true);
    expect(isEditKey({ key: 'Enter', ctrlKey: true })).toBe(false);
    expect(isEditKey({ key: 'Escape' })).toBe(false);
  });

  it('types printable characters only', () => {
    expect(printableKey({ key: '7' })).toBe('7');
    expect(printableKey({ key: 'ä' })).toBe('ä');
    expect(printableKey({ key: ' ' })).toBe(' ');
    expect(printableKey({ key: 'c', ctrlKey: true })).toBeNull();
    expect(printableKey({ key: 'v', metaKey: true })).toBeNull();
    expect(printableKey({ key: 'Tab' })).toBeNull();
    expect(printableKey({ key: 'ArrowDown' })).toBeNull();
    expect(printableKey({ key: 'a', isComposing: true })).toBeNull();
  });
});

describe('cell addresses', () => {
  const row = { source_row_number: 14 };
  it('names a cell by its source column letter and row number', () => {
    expect(cellAddress(row, { source_column_number: 4 })).toBe('D14');
    expect(cellAddress(row, { source_column_number: 28 })).toBe('AB14');
  });

  it('falls back to the cell source, then to the column header', () => {
    expect(cellAddress({ source_row_number: null }, { source_column_number: null }, { source: { a1: 'C3' } })).toBe('C3');
    expect(cellAddress(row, { source_column_number: null, original_header: 'Menge' })).toBe('Menge, row 14');
  });

  it('keys cells by row and column id and sorts columns by position', () => {
    expect(cellKey('row_1', 'col_a')).not.toBe(cellKey('row_1c', 'ol_a'));
    expect(sortColumns([{ position: 2, id: 'c' }, { position: 0, id: 'a' }, { position: 1, id: 'b' }]).map((c) => c.id)).toEqual([
      'a',
      'b',
      'c',
    ]);
  });
});

describe('cell text', () => {
  it('says how the app read a cell when that adds something', () => {
    const numberColumn = { inferred_type: 'number' };
    expect(readingNote({ data_type: 'text', parse_status: 'ambiguous', parse_note: 'Two readings.' }, numberColumn)).toBe('Two readings.');
    expect(readingNote({ data_type: 'text', parse_status: 'failed', parse_note: null }, numberColumn)).toBe('Not read as a number');
    expect(readingNote({ data_type: 'number', parse_status: 'exact', parse_note: null }, numberColumn)).toBeNull();
    expect(readingNote({ data_type: 'empty', parse_status: 'not_applicable', parse_note: null }, numberColumn)).toBeNull();
    expect(readingNote({ data_type: 'text', parse_status: 'exact', parse_note: null }, { inferred_type: 'text' })).toBeNull();
    expect(readingNote(null, numberColumn)).toBeNull();
  });

  it('cuts an explanation after its first sentence', () => {
    expect(firstSentence('The total is wrong. Check the price.')).toBe('The total is wrong.');
    expect(firstSentence('12.5 × 40.00 is not 520.00. Check it.')).toBe('12.5 × 40.00 is not 520.00.');
    expect(firstSentence('No sentence end')).toBe('No sentence end');
    expect(firstSentence(null)).toBe('');
  });
});
