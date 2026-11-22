import { screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { BidPosition, BidReminder, BidReport } from '../../services/apiTypes.ts';
import { errorResponse, mockFetch } from '../../test/fetchMock.ts';
import { documentSummary } from '../../test/fixtures.ts';
import { renderApp } from '../../test/render.tsx';
import { WORKSPACE_PROJECT } from '../../test/workspaceRoutes.ts';

const URL = '/api/v1/projects/prj_1/risk-report';
// Every page of a project loads the project once for its navigation.
const PROJECT = { path: '/api/v1/projects/prj_1', respond: { project: WORKSPACE_PROJECT, documents: [documentSummary], review_counts: {} } };

function reminder(overrides: Partial<BidReminder> = {}): BidReminder {
  return {
    risk_id: 'risk_0000000000000001',
    tier: 'high',
    state: 'risk',
    title: 'Concrete class not stated',
    risk_name: 'Missing value',
    positions_total: 1,
    money: { kind: 'unknown', amount: null, currency: null, low: null, high: null, basis: 'No amount.', reference: null },
    question: 'Which concrete class is meant?',
    suggested_action: 'Ask the client.',
    ...overrides,
  };
}

function position(overrides: Partial<BidPosition> = {}): BidPosition {
  return {
    rank: 1,
    kind: 'reminders',
    document_id: 'doc_1',
    document_name: 'Rohbau.x83',
    run_id: 'run_1',
    label: '01.02.0050',
    item_code: '01.02.0050',
    table_id: 't1',
    row_id: 'r1',
    short_text: 'Stahlbetonstütze S1',
    quantity: '3',
    unit: 'm3',
    unit_price: '300.00',
    line_total: '900.00',
    currency: 'EUR',
    share_of_total: '0.0278',
    reminders: [reminder()],
    ...overrides,
  };
}

const REPORT: BidReport = {
  project_id: 'prj_1',
  project_name: 'Riverside',
  generated_at: '2026-11-21T20:00:00Z',
  limit: 20,
  positions: [
    position(),
    position({
      rank: 2,
      label: '01.01.0020',
      row_id: 'r2',
      short_text: 'Stahlbetonwand W14',
      line_total: '2600.00',
      reminders: [
        reminder({
          risk_id: 'risk_0000000000000002',
          tier: 'medium',
          title: 'Line total does not match',
          money: { kind: 'exact', amount: '100.00', currency: 'EUR', low: null, high: null, basis: 'Computed.', reference: null },
          question: null,
        }),
      ],
    }),
    position({ rank: 3, kind: 'largest', label: '01.02.0010', row_id: 'r3', short_text: 'Stahlbetondecke D3', line_total: '6600.00', reminders: [] }),
  ],
  positions_with_reminders: 2,
  other_reminders: [
    {
      reason: 'many_positions',
      document_id: 'doc_1',
      document_name: 'Rohbau.x83',
      run_id: 'run_1',
      positions: ['02.0010', '02.0020', '02.0030', '02.0040'],
      reminder: reminder({ risk_id: 'risk_0000000000000003', tier: 'medium', title: 'Waterproofing not tied', positions_total: 12 }),
    },
  ],
  bills: [
    {
      document_id: 'doc_1',
      document_name: 'Rohbau.x83',
      run_id: 'run_1',
      run_status: 'completed',
      positions: 11,
      priced: true,
      currency: 'EUR',
      counted_total: '32340',
      reminders: 3,
      rejected: 0,
    },
  ],
  skipped: [{ document_id: 'doc_2', document_name: 'Referenz.x83', reason: 'Reference: compared, not validated as a bill' }],
  largest_share: '0.6679',
  order_basis: 'Positions named by reminders first.',
  notes: ['The 20 largest positions make up 66.8 % of the counted total of the priced bills.'],
};

describe('Bid risk report', () => {
  it('lists the positions with their line totals and the money of their reminders, and prints', async () => {
    mockFetch([PROJECT, { path: URL, respond: REPORT }]);
    const print = vi.spyOn(window, 'print').mockImplementation(() => {});
    const { user } = renderApp('/projects/prj_1/report');

    const table = await screen.findByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('01.02.0050');
    expect(rows[0]).toHaveTextContent('Concrete class not stated');
    expect(rows[0]).toHaveTextContent('Which concrete class is meant?');
    expect(rows[1]).toHaveTextContent('2,600.00 EUR');
    expect(rows[1]).toHaveTextContent('100.00 EUR');
    expect(rows[2]).toHaveTextContent('No reminder: listed for its size');
    expect(screen.getByText('2 of 2 positions with reminders')).toBeInTheDocument();

    const others = screen.getByRole('region', { name: 'Reminders about several positions' });
    expect(others).toHaveTextContent('Waterproofing not tied');
    expect(others).toHaveTextContent('Concerns 12 positions: 02.0010, 02.0020, 02.0030, 02.0040 …');
    expect(screen.getByText('Not in this report: Referenz.x83 (Reference: compared, not validated as a bill)')).toBeInTheDocument();
    expect(screen.getByText(/66.8 % of the counted total/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Bills in this report' })).toHaveTextContent('total 32,340.00 EUR');

    await user.click(screen.getByRole('button', { name: 'Print or save as PDF' }));
    expect(print).toHaveBeenCalledOnce();
  });

  it('says an unknown amount is a large share only about several positions together, never under one position', async () => {
    const large = { kind: 'unknown' as const, amount: null, currency: null, low: null, high: null, basis: 'No amount.', reference: null, size_class: 'large' };
    const report: BidReport = {
      ...REPORT,
      // A reminder whose other position is large: this small position is not "a large share".
      positions: [position({ share_of_total: '0.0009', reminders: [reminder({ positions_total: 2, money: large })] })],
      other_reminders: [
        { ...REPORT.other_reminders[0], reminder: reminder({ risk_id: 'risk_0000000000000003', positions_total: 12, money: large }) },
        { ...REPORT.other_reminders[0], reminder: reminder({ risk_id: 'risk_0000000000000004', positions_total: 12, money: { ...large, size_class: 'small' } }) },
      ],
    };
    mockFetch([PROJECT, { path: URL, respond: report }]);
    renderApp('/projects/prj_1/report');

    const [row] = within(await screen.findByRole('table')).getAllByRole('row').slice(1);
    expect(row).toHaveTextContent('0.1 % of the bill');
    expect(row).toHaveTextContent('Not known');
    expect(row).not.toHaveTextContent('share of the bill');
    const others = screen.getByRole('region', { name: 'Reminders about several positions' });
    expect(within(others).getAllByText('The positions concerned are a large share of the bill')).toHaveLength(1);
    expect(others).not.toHaveTextContent('small share');
  });

  it('asks to validate the project before it is validated, and leads back to the project', async () => {
    mockFetch([
      PROJECT,
      { path: URL, respond: errorResponse(409, 'conflict', "Project 'prj_1' has not been validated: validate it first.") },
      // The overview it leads to lists the follow-ups.
      { path: '/api/v1/projects/prj_1/clarifications', respond: { items: [], total: 0, offset: 0, limit: 10 } },
    ]);
    const { user, location } = renderApp('/projects/prj_1/report');
    expect(await screen.findByRole('heading', { name: 'Validate the project to see its bid risk report' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open the project overview' }));
    expect(location()).toBe('/projects/prj_1');
  });
});
