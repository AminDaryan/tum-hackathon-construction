import { describe, expect, it } from 'vitest';
import { cellIndex } from './cellIndex.ts';
import type { ValidationIssue } from '../../services/apiTypes.ts';

describe('cellIndex', () => {
  it('lists every finding of a cell and of a row, strongest first', () => {
    const cell = { table_id: 't', row_id: 'r', column_id: 'c' };
    const low = { issue_id: 'a', severity: 'low', table_id: 't', row_id: 'r', affected_cells: [cell] };
    const high = { issue_id: 'b', severity: 'high', table_id: 't', row_id: 'r', affected_cells: [cell] };
    // Test findings: only what the index and its order read.
    const index = cellIndex([low, high] as ValidationIssue[]);
    expect(index.forCell('t', 'r', 'c').map((issue) => issue.issue_id)).toEqual(['b', 'a']);
    expect(index.forRow('t', 'r')).toHaveLength(2);
    expect(index.forCell('t', 'r', 'x')).toEqual([]);
  });
});
