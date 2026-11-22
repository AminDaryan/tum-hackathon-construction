import { describe, expect, it } from 'vitest';
import { lineTotalIssue, outlierIssue, riskReport, rows, table } from '../../test/fixtures.ts';
import {
  difference,
  findingsOnRow,
  isPriced,
  lineTotalFor,
  percentBetween,
  priceComparisons,
  priceFacts,
  isPriceRisk,
  rangePositions,
} from './pricing.ts';

const pricedRow = {
  ...rows[1],
  cells: {
    ...rows[1].cells,
    col_qty: { raw_value: '12.5', normalized_value: { kind: 'number', value: '12.5' } },
    col_price: { raw_value: '40,00', normalized_value: { kind: 'number', value: '40.00' } },
    col_total: { raw_value: '520.00', normalized_value: { kind: 'number', value: '520.00' } },
  },
};

const peerIssue = {
  ...outlierIssue,
  issue_id: 'iss_peer',
  detector_id: 'statistical.peer_price',
  evidence: [
    {
      kind: 'comparison',
      label: 'Comparable positions',
      detail: '7.9 robust scales above the median of 3 positions',
      cells: [],
      data: { peers: 3, median: '16.00', lowest: '12.00', highest: '20.00' },
      calculation: null,
    },
  ],
};

const identicalIssue = {
  ...outlierIssue,
  issue_id: 'iss_same',
  detector_id: 'statistical.rate_consistency',
  evidence: [{ kind: 'comparison', label: 'Identical positions', detail: '02.001 at 635.00', cells: [], data: { reference: '635.00' }, calculation: null }],
};

describe('pricing', () => {
  it('reads the figures of a row from the mapped columns, numbers from their normalized value', () => {
    const facts = priceFacts(pricedRow, table);
    expect(facts).toMatchObject({ rowId: 'row_5', tableId: 'tbl_1', quantity: '12.5', unitPrice: '40.00', lineTotal: '520.00' });
    expect(facts!.columns).toMatchObject({ unit_price: 'col_price', line_total: 'col_total', discount_percent: null });
    expect(isPriced(facts)).toBe(true);
    // The fixture's own row has no settled numbers (its unit price "1,234" is ambiguous).
    expect(isPriced(priceFacts(rows[1], table))).toBe(false);
    expect(priceFacts(null, table)).toBeNull();
  });

  it('computes the line total rounded to cents, the discount taken off the rounded total', () => {
    expect(lineTotalFor('12.5', '40.00')).toBe('500.00');
    expect(lineTotalFor('3', '0.335')).toBe('1.01');
    expect(lineTotalFor('10', '9.99', '3')).toBe('96.90');
    expect(lineTotalFor('x', '1')).toBeNull();
    expect(difference('520.00', '500.00')).toBe('-20.00');
    expect(percentBetween('578.29', '10')).toBe('-98.3');
  });

  it('reads comparable and identical positions from the findings of the price checks', () => {
    const { peer, identical, others } = priceComparisons([peerIssue, identicalIssue, lineTotalIssue]);
    expect(peer).toMatchObject({ peers: 3, median: '16.00', lowest: '12.00', highest: '20.00' });
    expect(identical).toMatchObject({ reference: '635.00', detail: '02.001 at 635.00' });
    expect(others).toEqual([]);
    expect(findingsOnRow([lineTotalIssue, peerIssue], 'row_5')).toHaveLength(2);
    expect(findingsOnRow([lineTotalIssue], 'row_9')).toEqual([]);
  });

  it('knows a risk about a price: a comparison, money on prices or quantities, or a price check', () => {
    const [totalRisk, priceRisk, soilRisk] = riskReport.risks;
    expect(isPriceRisk(priceRisk, new Map())).toBe(true);
    expect(isPriceRisk(totalRisk, new Map())).toBe(true);
    expect(isPriceRisk(soilRisk, new Map())).toBe(false);
    const checked = { ...soilRisk, source_issue_ids: ['iss_peer'] };
    expect(isPriceRisk(checked, new Map([['iss_peer', peerIssue]]))).toBe(true);
    expect(isPriceRisk(null, new Map())).toBe(false);
  });

  it('places the marks of the range bar on a linear scale from zero', () => {
    expect(rangePositions({ lowest: '12', highest: '20', median: '16', current: '40' })).toEqual({
      lowest: 0.3,
      highest: 0.5,
      median: 0.4,
      current: 1,
    });
    expect(rangePositions({ lowest: null, current: null })).toBeNull();
  });
});
