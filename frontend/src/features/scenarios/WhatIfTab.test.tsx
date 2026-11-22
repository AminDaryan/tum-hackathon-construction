import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { dataset as sourceDataset, documentDetail, rows } from '../../test/fixtures.ts';
import { mockFetch, page, type MockCall } from '../../test/fetchMock.ts';
import type { Cell, Column, Row } from '../../services/apiTypes.ts';
import { WhatIfTab } from './WhatIfTab.tsx';

// The fixture bill has an item row.
const source = rows.find((row) => row.classification.kind === 'item')!;
const dataset = { ...sourceDataset, tables: sourceDataset.tables.map((table) => ({ ...table,
  // Test column: only what the scenario reads.
  columns: [...table.columns, { column_id: 'col_unit', mapped_semantic_field: 'unit' } as Column],
})) };
function item(id: string, text: string, price: string, included = true): Row {
  // Test cells: only what the scenario reads.
  const cell = (value: string | null) => ({ normalized_value: { kind: 'number', value }, raw_value: value }) as Cell;
  return { ...source, row_id: id, classification: { ...source.classification, counts_toward_totals: included }, cells: {
    ...source.cells, col_text: { raw_value: text } as Cell, col_unit: { raw_value: 't' } as Cell, col_qty: cell('2'), col_price: cell(price), col_total: cell(`${Number(price) * 2}.00`),
  } };
}
const bill = [item('s1', 'Steel S355', '10'), item('s2', 'Steel S355', '20'), item('alt', 'Optional concrete', '7', false), item('concrete', 'Concrete', '5')];
function routes(revision = 1) {
  return [
    { path: '/api/v1/datasets/ds_1/tables/tbl_1/rows', respond: (call: MockCall) => {
      const offset = Number(call.query.get('offset'));
      return page(bill.slice(offset, offset + 2), { total: bill.length });
    } },
    { path: '/api/v1/documents/doc_1', respond: { ...documentDetail, dataset: { ...dataset, revision } } },
  ];
}

it('pages the complete bill, allows match review and optional swaps, and reloads named immutable versions without writing the BoQ', async () => {
  const api = mockFetch(routes());
  const user = userEvent.setup();
  const { unmount } = render(<WhatIfTab dataset={dataset} revision={1} />);
  await screen.findByRole('heading', { name: 'Net bid comparison' });
  const comparison = screen.getByRole('heading', { name: 'Net bid comparison' }).closest('[aria-live]');
  expect(comparison).toHaveTextContent('Before70.00 EURAfter70.00 EURChange0.00 EUR');
  const picker = screen.getByRole('combobox', { name: 'Material or specification' });
  await user.click(picker);
  expect(await screen.findByRole('option', { name: /^Steel S355/ })).toBeInTheDocument();
  expect(screen.getByRole('option', { name: /^Concrete/ })).toBeInTheDocument();
  await user.type(picker, 'ste');
  expect(screen.queryByRole('option', { name: /^Concrete/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole('option', { name: /^Steel S355/ }));
  expect(screen.getByText('2 positions selected')).toBeInTheDocument();
  expect(within(screen.getByRole('list', { name: 'Positions' })).getAllByRole('checkbox')).toHaveLength(2);
  await user.click(screen.getByRole('button', { name: 'Clear material or specification' }));
  expect(picker).toHaveValue('');
  expect(screen.getByText('2 positions selected')).toBeInTheDocument();
  expect(within(screen.getByRole('list', { name: 'Positions' })).getAllByRole('checkbox')).toHaveLength(4);
  expect(screen.getAllByRole('checkbox', { name: 'Price rule match' })[0]).toBeChecked();
  expect(screen.getAllByRole('checkbox', { name: 'Price rule match' })[1]).toBeChecked();
  // A reviewer rejects one suggested match; the other row keeps its original price.
  const matches = screen.getAllByRole('checkbox', { name: 'Price rule match' });
  await user.click(matches[1]);
  await user.click(screen.getByRole('button', { name: 'Add price rule' }));
  expect(comparison).toHaveTextContent('After73.00 EURChange3.00 EUR');
  const include = screen.getAllByRole('checkbox', { name: 'Include in scenario bid' });
  await user.click(include[1]);
  await user.click(include[2]);
  expect(comparison).toHaveTextContent('Before70.00 EURAfter47.00 EURChange-23.00 EUR');
  await user.type(screen.getByRole('textbox', { name: 'Scenario name' }), 'Steel swap');
  await user.click(screen.getByRole('button', { name: 'Save scenario' }));
  expect(screen.getByRole('status')).toHaveTextContent('Saved locally as version 1.');
  await user.click(screen.getByRole('button', { name: 'Remove rule 1' }));
  await user.click(screen.getByRole('button', { name: 'Save scenario' }));
  expect(screen.getByRole('status')).toHaveTextContent('Saved locally as version 2.');
  unmount();
  // The working draft survives leaving the tab (or a reload) in this browser tab.
  render(<WhatIfTab dataset={dataset} revision={1} />);
  await screen.findByRole('heading', { name: 'Net bid comparison' });
  expect(screen.getByRole('heading', { name: 'Net bid comparison' }).closest('[aria-live]')).toHaveTextContent('After44.00 EUR');
  expect(screen.getByRole('textbox', { name: 'Scenario name' })).toHaveValue('Steel swap');
  await user.click(screen.getByRole('button', { name: /Load saved version/ }));
  await user.click(screen.getByRole('option', { name: 'Steel swap / v1' }));
  const restored = screen.getByRole('heading', { name: 'Net bid comparison' }).closest('[aria-live]');
  expect(restored).toHaveTextContent('Before70.00 EURAfter47.00 EURChange-23.00 EUR');
  expect(api.calls.every((call) => call.method === 'GET')).toBe(true);
  expect(screen.getByRole('status')).toHaveTextContent('Loaded Steel swap / v1.');
  await user.click(screen.getByRole('button', { name: /All positions/ }));
  await user.click(screen.getByRole('option', { name: 'Changed' }));
  expect(within(screen.getByRole('list', { name: 'Positions' })).getAllByRole('listitem')).toHaveLength(3);
});

it('rejects a changed source revision rather than combining current rows with stale metadata', async () => {
  mockFetch(routes(2));
  render(<WhatIfTab dataset={dataset} revision={1} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load a consistent bill revision');
  expect(screen.queryByRole('heading', { name: 'Net bid comparison' })).not.toBeInTheDocument();
});

it('clears only the material filter while keeping search, display filter and scenario data', async () => {
  mockFetch(routes());
  const user = userEvent.setup();
  render(<WhatIfTab dataset={dataset} revision={1} />);
  const picker = await screen.findByRole('combobox', { name: 'Material or specification' });
  await user.click(picker);
  await user.click(await screen.findByRole('option', { name: /^Steel S355/ }));
  await user.type(screen.getByRole('textbox', { name: 'Scenario name' }), 'Keep me');
  await user.type(screen.getByRole('searchbox', { name: 'Search positions' }), 'Concrete');
  await user.click(screen.getByRole('button', { name: /Rule matches/ }));
  await user.click(screen.getByRole('option', { name: 'Optional and alternatives' }));
  const before = JSON.parse(sessionStorage.getItem('twb.whatIf.draft.v1.ds_1.1')!);
  await user.click(screen.getByRole('button', { name: 'Clear material or specification' }));
  expect(screen.getByRole('searchbox', { name: 'Search positions' })).toHaveValue('Concrete');
  expect(screen.getByRole('button', { name: /Optional and alternatives/ })).toBeInTheDocument();
  expect(JSON.parse(sessionStorage.getItem('twb.whatIf.draft.v1.ds_1.1')!)).toEqual({ ...before, materialId: '', query: '' });
});
