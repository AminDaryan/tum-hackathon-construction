import { describe, expect, it } from 'vitest';
import { mockFetch, page } from '../../test/fetchMock.ts';
import { cellRef, lineTotalIssue, outlierIssue } from '../../test/fixtures.ts';
import { compareFindings, indexFindings, loadRunFindings } from './runFindings.ts';
import type { ValidationIssue } from '../../services/apiTypes.ts';

function finding(
  id: string,
  detectorId: string,
  severity: ValidationIssue['severity'],
  evidenceClass: ValidationIssue['effective_evidence_class'],
  extra: Partial<ValidationIssue> = {},
): ValidationIssue {
  return {
    ...outlierIssue,
    issue_id: id,
    detector_id: detectorId,
    severity,
    effective_evidence_class: evidenceClass,
    ...extra,
  };
}

describe('compareFindings', () => {
  it('ranks a reviewer-confirmed error above a rule violation of the same severity', () => {
    const confirmed = finding('a', 'x', 'medium', 'human_confirmed_error');
    const violation = finding('b', 'y', 'medium', 'confirmed_rule_violation');
    const anomaly = finding('c', 'z', 'high', 'suspected_anomaly');
    expect([violation, confirmed, anomaly].sort(compareFindings)).toEqual([anomaly, confirmed, violation]);
  });
});

describe('indexFindings', () => {
  it('finds a finding by its row and by every row and cell it highlights', () => {
    const gap = finding('gap', 'domain.boq_numbering', 'low', 'suspected_anomaly', {
      row_id: null,
      affected_cells: [cellRef('row_4', 'col_pos', 4), cellRef('row_6', 'col_pos', 6)],
    });
    const index = indexFindings([lineTotalIssue, outlierIssue, gap]);
    expect(index.size).toBe(3);
    expect(index.forRow('tbl_1', 'row_5').map((issue) => issue.issue_id)).toEqual(['iss_1', 'iss_2']);
    expect(index.forRow('tbl_1', 'row_4')).toEqual([gap]);
    expect(index.forRow('tbl_1', 'row_6')).toEqual([gap]);
    expect(index.forRow('tbl_2', 'row_5')).toEqual([]);
    expect(index.forCell('tbl_1', 'row_5', 'col_total')).toBe(lineTotalIssue);
    expect(index.forCell('tbl_1', 'row_5', 'col_price')).toBe(outlierIssue);
    expect(index.forCell('tbl_1', 'row_5', 'col_qty')).toBeNull(); // an input cell is not highlighted
  });

  it('keeps the strongest finding of a cell that several highlight', () => {
    const weak = finding('weak', 'domain.boq_typos', 'low', 'semantic_warning', {
      affected_cells: [cellRef('row_5', 'col_total', 5)],
    });
    expect(indexFindings([weak, lineTotalIssue]).forCell('tbl_1', 'row_5', 'col_total')).toBe(lineTotalIssue);
  });
});

describe('loadRunFindings', () => {
  it('pages through the findings 500 at a time, up to the cap', async () => {
    const total = 1200;
    const api = mockFetch([
      {
        path: '/api/v1/validation-runs/run_2/issues',
        respond: (call) => {
          const offset = Number(call.query.get('offset'));
          const limit = Number(call.query.get('limit'));
          const count = Math.max(0, Math.min(limit, total - offset));
          return page(
            Array.from({ length: count }, (_, i) => ({ ...lineTotalIssue, issue_id: `iss_${offset + i}` })),
            { total, offset, limit },
          );
        },
      },
    ]);

    const all = await loadRunFindings('run_2');
    expect(all.total).toBe(1200);
    expect(all.items).toHaveLength(1200);
    expect(api.callsTo('GET', '/api/v1/validation-runs/run_2/issues').map((call) => call.query.toString())).toEqual([
      'offset=0&limit=500',
      'offset=500&limit=500',
      'offset=1000&limit=500',
    ]);

    const capped = await loadRunFindings('run_2', { max: 600 });
    expect(capped.items).toHaveLength(600);
    expect(capped.total).toBe(1200);
  });
});
