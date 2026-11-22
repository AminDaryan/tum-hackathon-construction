import { describe, expect, it } from 'vitest';
import type { SourceLocation } from '../services/apiTypes.ts';
import { describeSource, formatCellReference } from './sourceLocation.ts';

describe('source locations', () => {
  it('names a GAEB cell by table row, column and XML line', () => {
    const source: SourceLocation = { kind: 'gaeb_xml', sheet_name: 'LV', row_number: 12, column_number: 4, line_number: 345 };
    expect(formatCellReference(source)).toBe('row 12, column 4, XML line 345');
    expect(describeSource(source)).toBe('GAEB row 12, column 4, XML line 345');
    expect(describeSource({ kind: 'gaeb_xml' })).toBe('GAEB');
    expect(formatCellReference({ kind: 'gaeb_xml' })).toBeNull();
  });

  it('names a GAEB 90 cell by table row, column and file line', () => {
    const source: SourceLocation = { kind: 'gaeb_90', sheet_name: 'LV', row_number: 12, column_number: 4, line_number: 345 };
    expect(formatCellReference(source)).toBe('row 12, column 4, line 345');
    expect(describeSource(source)).toBe('GAEB 90 row 12, column 4, line 345');
    expect(describeSource({ kind: 'gaeb_90' })).toBe('GAEB 90');
  });

  it('names a Word table cell by table, row and column, and an item paragraph by its number', () => {
    const cell: SourceLocation = { kind: 'word', sheet_name: 'Table 2', row_number: 5, column_number: 3 };
    expect(formatCellReference(cell)).toBe('Table 2, row 5, column 3');
    expect(describeSource(cell)).toBe('Word Table 2, row 5, column 3');
    const item: SourceLocation = { kind: 'word', sheet_name: 'LV', row_number: 7, column_number: 2, line_number: 31 };
    expect(formatCellReference(item)).toBe('paragraph 31');
    expect(describeSource(item)).toBe('Word paragraph 31');
    expect(describeSource({ kind: 'word' })).toBe('Word');
  });

  it('keeps spreadsheet and CSV references', () => {
    expect(formatCellReference({ kind: 'spreadsheet', sheet_name: 'Bill 1', row_number: 12, column_number: 3 })).toBe(
      "'Bill 1'!C12",
    );
    expect(describeSource({ kind: 'delimited_text', row_number: 14, column_number: 3 })).toBe('CSV record 14, field 3');
  });
});
