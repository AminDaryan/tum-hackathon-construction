import { describe, expect, it } from 'vitest';
import { issueTarget } from './issueTarget.ts';

describe('issueTarget', () => {
  it('prefers the affected cell, then an input cell, then the row', () => {
    const cell = { table_id: 'tbl_1', row_id: 'row_5', column_id: 'col_total' };
    expect(issueTarget({ affected_cells: [cell] })).toEqual({ tableId: 'tbl_1', rowId: 'row_5', columnId: 'col_total' });
    expect(issueTarget({ affected_cells: [], input_cells: [cell] })).toEqual({ tableId: 'tbl_1', rowId: 'row_5', columnId: 'col_total' });
    expect(issueTarget({ affected_cells: [], table_id: 'tbl_1', row_id: 'row_7' })).toEqual({ tableId: 'tbl_1', rowId: 'row_7', columnId: null });
  });

  it('has no target for a finding about the whole table', () => {
    expect(issueTarget({ affected_cells: [], table_id: 'tbl_1', row_id: null })).toBeNull();
    expect(issueTarget(null)).toBeNull();
  });
});
