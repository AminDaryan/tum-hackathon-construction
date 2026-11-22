import { render, screen, waitFor, within } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { chooseOption } from '../../../test/select.ts';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { errorResponse, mockFetch, type MockCall } from '../../../test/fetchMock.ts';
import { cellRef, lineTotalIssue, outlierIssue, rows, rowsPage, table } from '../../../test/fixtures.ts';
import type { Row } from '../../../services/apiTypes.ts';
import { cellIndex } from '../cellIndex.ts';
import { Sheet } from './Sheet.tsx';

const ROWS = '/api/v1/datasets/ds_1/tables/tbl_1/rows';
const CORRECTIONS = '/api/v1/datasets/ds_1/corrections';
const COLUMN_INDEX: Readonly<Record<string, number>> = { A: 0, B: 1, C: 2, E: 3, F: 4 };

/** Rows with source numbers 4, 5, ... (ids row_4, row_5, ...), for paging. */
function manyRows(count: number) {
  return Array.from({ length: count }, (_, index) => {
    const number = index + 4;
    return {
      ...rows[1],
      row_id: `row_${number}`,
      position: index,
      source_row_number: number,
      cells: {
        col_pos: { ...rows[1].cells.col_pos, raw_value: `01.${number}` },
        col_text: { ...rows[1].cells.col_text, raw_value: `Position ${number}` },
      },
    };
  });
}

/** The rows endpoint over `all`: by offset, or the page holding `row_id`. */
function pagedRows(all: Row[]) {
  return (call: MockCall) => {
    const limit = Number(call.query.get('limit'));
    const rowId = call.query.get('row_id');
    let offset = Number(call.query.get('offset') ?? 0);
    if (rowId) {
      const index = all.findIndex((row) => row.row_id === rowId);
      if (index < 0) return errorResponse(404, 'not_found', `Row ${rowId} was not found.`);
      offset = Math.floor(index / limit) * limit;
    }
    return { items: all.slice(offset, offset + limit), total: all.length, offset, limit };
  };
}

function revised(revision: number, rowList: Row[]) {
  return { dataset_id: 'ds_1', revision, parent_revision: revision - 1, changed: rowList.length, rows: rowList };
}

function withCell(row: Row, columnId: string, rawValue: string): Row {
  return { ...row, cells: { ...row.cells, [columnId]: { ...row.cells[columnId], raw_value: rawValue } } };
}

function deferred() {
  // Set by the promise's executor, which runs at once.
  let resolve!: (value: unknown) => void;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function renderSheet(props: Partial<ComponentProps<typeof Sheet>> = {}) {
  const user = userEvent.setup();
  const handlers = {
    onRevised: vi.fn(),
    onReload: vi.fn(),
    onReview: vi.fn(),
    onRowsLoaded: vi.fn<(rows: Row[]) => void>(),
    onTableChange: vi.fn(),
  };
  const base = { datasetId: 'ds_1', table, tables: [table], revision: 3, ...handlers, ...props };
  const view = render(<Sheet {...base} />);
  return {
    user,
    ...handlers,
    rerender: (next: Partial<ComponentProps<typeof Sheet>>) => view.rerender(<Sheet {...base} {...next} />),
  };
}

/** The grid cell at an A1 address of the fixture table (columns A, B, C, E, F). */
function cellAt(address: string) {
  const match = /^([A-Z]+)(\d+)$/.exec(address);
  if (!match) throw new Error(`${address} is not an A1 address`);
  const [, letter, number] = match;
  const grid = screen.getByRole('grid');
  const row = within(grid)
    .getAllByRole('row')
    .find((candidate) => new RegExp(`^${number}(,|$)`).test(within(candidate).queryByRole('rowheader')?.textContent ?? ''));
  if (!row) throw new Error(`Row ${number} is not on the page`);
  return within(row).getAllByRole('gridcell')[COLUMN_INDEX[letter]];
}

function cellBar() {
  return screen.getByRole('group', { name: 'Active cell' });
}

describe('Sheet', () => {
  it('shows column letters, the file headers and the source row numbers', async () => {
    const api = mockFetch([{ path: ROWS, respond: rowsPage }]);
    const { onRowsLoaded } = renderSheet({ actions: <button type="button">Attach model</button> });

    const grid = await screen.findByRole('grid', { name: 'Sheet LV' });
    expect(screen.getByRole('heading', { name: 'LV' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Attach model' })).toBeInTheDocument();
    expect(grid).toHaveAttribute('aria-rowcount', '5');
    const [letters, headers, ...body] = within(grid).getAllByRole('row');
    expect(within(letters).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['', 'A', 'B', 'C', 'E', 'F']);
    expect(within(headers).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      'Row',
      'Pos.',
      'Kurztext',
      'Menge',
      'Einheitspreis',
      'Gesamtpreis',
    ]);
    expect(within(headers).getByRole('columnheader', { name: 'Menge' })).toHaveAttribute('title', 'Read as quantity');
    expect(body.map((row) => within(row).getByRole('rowheader').textContent)).toEqual(['4', '5', '6']);
    expect(body[0]).toHaveClass('font-semibold');
    expect(body[2]).toHaveClass('font-semibold');
    expect(body[1]).not.toHaveClass('font-semibold');
    expect(cellAt('B5')).toHaveTextContent('Oberboden abtragen');
    expect(cellAt('C5')).toHaveClass('text-right');
    expect(within(cellAt('E5')).getByRole('button', { name: 'Parse status: Ambiguous' })).toHaveAttribute('tabindex', '-1');
    expect(cellAt('A4')).toHaveAttribute('tabindex', '0');
    expect(cellAt('B4')).toHaveAttribute('tabindex', '-1');
    // Nothing is selected yet: the cell bar says nothing, rather than "No cell selected".
    expect(cellBar().textContent).toBe('');
    expect(screen.getByRole('navigation', { name: 'rows pages' })).toHaveTextContent('1–3 of 3 rows');
    expect(api.callsTo('GET', ROWS)[0].query.toString()).toBe('offset=0&limit=100');
    // onRowsLoaded runs in an effect after the rows are drawn, so it may come a moment later.
    await waitFor(() =>
      expect(onRowsLoaded).toHaveBeenLastCalledWith(expect.arrayContaining([expect.objectContaining({ row_id: 'row_5' })])),
    );
  });

  it('pages through the rows 100 at a time', async () => {
    const api = mockFetch([{ path: ROWS, respond: pagedRows(manyRows(250)) }]);
    const { user } = renderSheet({ table: { ...table, row_count: 250 } });

    await screen.findByRole('rowheader', { name: '4' });
    expect(screen.getAllByRole('rowheader')).toHaveLength(100);
    expect(screen.getByRole('navigation', { name: 'rows pages' })).toHaveTextContent('1–100 of 250 rows');

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('rowheader', { name: '104' });
    expect(screen.queryByRole('rowheader', { name: '4' })).not.toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'rows pages' })).toHaveTextContent('101–200 of 250 rows');
    expect(screen.getByRole('row', { name: /^104/ })).toHaveAttribute('aria-rowindex', '103');
    expect(api.callsTo('GET', ROWS).at(-1)?.query.toString()).toBe('offset=100&limit=100');
  });

  it('moves the active cell with the arrow keys, Home and End, and shows it in the cell bar', async () => {
    mockFetch([{ path: ROWS, respond: rowsPage }]);
    const { user } = renderSheet();
    await screen.findByRole('grid');

    await user.click(cellAt('A4'));
    expect(cellAt('A4')).toHaveFocus();
    expect(cellBar()).toHaveTextContent('A4');
    expect(cellBar()).toHaveTextContent('01');

    await user.keyboard('{ArrowRight}');
    expect(cellAt('B4')).toHaveFocus();
    expect(cellBar()).toHaveTextContent('Erdarbeiten');
    await user.keyboard('{ArrowDown}');
    expect(cellAt('B5')).toHaveFocus();
    await user.keyboard('{End}');
    expect(cellAt('F5')).toHaveFocus();
    await user.keyboard('{ArrowLeft}');
    expect(cellAt('E5')).toHaveFocus();
    expect(cellBar()).toHaveTextContent('1,234 could be 1.234 or 1234; no value was chosen.');
    await user.keyboard('{Home}');
    expect(cellAt('A5')).toHaveFocus();
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(cellAt('A6')).toHaveFocus();
    expect(cellBar()).toHaveTextContent('Empty cell');

    // Roving tab stop: only the active cell is in the Tab order, and Tab leaves the grid.
    expect(screen.getByRole('grid').querySelectorAll('[tabindex="0"]')).toHaveLength(1);
    expect(cellAt('A6')).toHaveAttribute('tabindex', '0');
    await user.tab();
    // Focus is on an HTML element of the page.
    expect(screen.getByRole('grid')).not.toContainElement(document.activeElement as HTMLElement | null);
  });

  it('saves an edit made after a double-click with the expected revision', async () => {
    const answer = deferred();
    const api = mockFetch([
      { path: ROWS, respond: rowsPage },
      { method: 'POST', path: CORRECTIONS, respond: () => answer.promise },
    ]);
    const { user, onRevised, onRowsLoaded } = renderSheet();
    await screen.findByRole('grid');

    await user.dblClick(cellAt('C5'));
    const editor = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Edit C5' });
    expect(editor).toHaveFocus();
    expect(editor).toHaveValue('12.5');
    expect([editor.selectionStart, editor.selectionEnd]).toEqual([0, 4]);
    await user.clear(editor);
    await user.keyboard('15{Enter}');

    expect(JSON.parse(api.callsTo('POST', CORRECTIONS)[0].body)).toEqual({
      expected_revision: 3,
      corrections: [{ table_id: 'tbl_1', row_id: 'row_5', column_id: 'col_qty', raw_value: '15' }],
    });
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(cellAt('C5')).toHaveAttribute('aria-busy', 'true');
    expect(cellAt('C5')).toHaveTextContent('15');
    expect(cellAt('C5')).toHaveFocus();

    answer.resolve(revised(4, [withCell(rows[1], 'col_qty', '15')]));
    expect(await screen.findByText('Saved C5 as revision 4. The uploaded file is not changed.')).toBeInTheDocument();
    expect(cellAt('C5')).not.toHaveAttribute('aria-busy');
    expect(cellAt('C5')).toHaveTextContent('15');
    expect(onRevised).toHaveBeenCalledWith(expect.objectContaining({ revision: 4, changed: 1 }));
    await waitFor(() => {
      const lastRows = onRowsLoaded.mock.lastCall?.[0];
      expect(lastRows?.find((row) => row.row_id === 'row_5')?.cells.col_qty.raw_value).toBe('15');
    });
  });

  it('cancels an edit with Escape and sends nothing for unchanged text', async () => {
    const api = mockFetch([{ path: ROWS, respond: rowsPage }]);
    const { user } = renderSheet();
    await screen.findByRole('grid');

    await user.dblClick(cellAt('B5'));
    const editor = screen.getByRole('textbox', { name: 'Edit B5' });
    await user.clear(editor);
    await user.keyboard('Neu{Escape}');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(cellAt('B5')).toHaveTextContent('Oberboden abtragen');
    expect(cellAt('B5')).toHaveFocus();

    await user.keyboard('{F2}');
    expect(screen.getByRole('textbox', { name: 'Edit B5' })).toHaveValue('Oberboden abtragen');
    await user.keyboard('{Enter}');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(api.callsTo('POST', CORRECTIONS)).toHaveLength(0);
    expect(screen.getByRole('status', { name: '' })).toBeEmptyDOMElement();
  });

  it('starts editing by typing and saves with Tab, moving right', async () => {
    const api = mockFetch([
      { path: ROWS, respond: rowsPage },
      { method: 'POST', path: CORRECTIONS, respond: revised(4, [withCell(rows[1], 'col_qty', '7')]) },
    ]);
    const { user } = renderSheet();
    await screen.findByRole('grid');

    await user.click(cellAt('C5'));
    await user.keyboard('7');
    const editor = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Edit C5' });
    expect(editor).toHaveValue('7');
    await user.keyboard('{Tab}');

    expect(JSON.parse(api.callsTo('POST', CORRECTIONS)[0].body).corrections[0]).toEqual({
      table_id: 'tbl_1',
      row_id: 'row_5',
      column_id: 'col_qty',
      raw_value: '7',
    });
    expect(cellAt('E5')).toHaveFocus();
    expect(await screen.findByText(/^Saved C5 as revision 4\./)).toBeInTheDocument();
  });

  it('says a stale revision was changed elsewhere and reloads the table on request', async () => {
    const api = mockFetch([
      { path: ROWS, respond: rowsPage },
      {
        method: 'POST',
        path: CORRECTIONS,
        respond: (call) =>
          JSON.parse(call.body).expected_revision === 5
            ? revised(6, [withCell(rows[1], 'col_qty', '16')])
            : errorResponse(409, 'conflict', 'The table is at revision 5; the change was made on revision 3.', {
                details: { dataset_id: 'ds_1', expected_revision: 3, current_revision: 5 },
              }),
      },
    ]);
    const { user, onReload, onRevised } = renderSheet();
    await screen.findByRole('grid');

    await user.dblClick(cellAt('C5'));
    await user.clear(screen.getByRole('textbox', { name: 'Edit C5' }));
    await user.keyboard('15{Enter}');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'This table was changed somewhere else and is now at revision 5. Reload the table to continue.',
    );
    expect(cellAt('C5')).toHaveTextContent('12.5');
    expect(onRevised).not.toHaveBeenCalled();

    await user.click(within(alert).getByRole('button', { name: 'Reload table' }));
    expect(onReload).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(api.callsTo('GET', ROWS)).toHaveLength(2));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    await user.dblClick(cellAt('C5'));
    await user.clear(screen.getByRole('textbox', { name: 'Edit C5' }));
    await user.keyboard('16{Enter}');
    expect(await screen.findByText('Saved C5 as revision 6. The uploaded file is not changed.')).toBeInTheDocument();
    expect(JSON.parse(api.callsTo('POST', CORRECTIONS)[1].body).expected_revision).toBe(5);
  });

  it('shows the API message when a save fails otherwise', async () => {
    mockFetch([
      { path: ROWS, respond: rowsPage },
      { method: 'POST', path: CORRECTIONS, respond: errorResponse(422, 'invalid_input', 'The text is longer than 32767 characters.') },
    ]);
    const { user } = renderSheet();
    await screen.findByRole('grid');

    await user.dblClick(cellAt('B5'));
    await user.keyboard('x{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('B5 was not saved. The text is longer than 32767 characters.');
    expect(screen.queryByRole('button', { name: 'Reload table' })).not.toBeInTheDocument();
    expect(cellAt('B5')).toHaveTextContent('Oberboden abtragen');
  });

  it('undoes the last saved edit by sending the previous text back', async () => {
    const api = mockFetch([
      { path: ROWS, respond: rowsPage },
      {
        method: 'POST',
        path: CORRECTIONS,
        respond: (call) => {
          const { expected_revision: expected, corrections } = JSON.parse(call.body);
          return revised(expected + 1, [withCell(rows[1], 'col_qty', corrections[0].raw_value)]);
        },
      },
    ]);
    const { user, onRevised } = renderSheet();
    await screen.findByRole('grid');

    await user.dblClick(cellAt('C5'));
    await user.clear(screen.getByRole('textbox', { name: 'Edit C5' }));
    await user.keyboard('15{Enter}');
    await screen.findByText('Saved C5 as revision 4. The uploaded file is not changed.');

    await user.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Restored the previous text of C5 as revision 5.')).toBeInTheDocument();
    expect(JSON.parse(api.callsTo('POST', CORRECTIONS)[1].body)).toEqual({
      expected_revision: 4,
      corrections: [{ table_id: 'tbl_1', row_id: 'row_5', column_id: 'col_qty', raw_value: '12.5' }],
    });
    expect(cellAt('C5')).toHaveTextContent('12.5');
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
    expect(onRevised).toHaveBeenCalledTimes(2);
  });

  it('washes cells with open findings red and rings the selected issue', async () => {
    mockFetch([{ path: ROWS, respond: rowsPage }]);
    const rejected = {
      ...outlierIssue,
      issue_id: 'iss_3',
      row_id: 'row_4',
      affected_cells: [cellRef('row_4', 'col_text', 4)],
      review_status: 'false_positive',
    };
    renderSheet({ findingsIndex: cellIndex([lineTotalIssue, outlierIssue, rejected]), selectedIssue: lineTotalIssue });
    await screen.findByRole('grid');

    expect(cellAt('E5')).toHaveClass('bg-issue-cell');
    expect(cellAt('E5')).toHaveTextContent(', 1 finding');
    expect(cellAt('F5')).toHaveClass('bg-issue-cell-strong');
    expect(cellAt('F5').className).toMatch(/inset_0_0_0_2px_var\(--color-violation\)/);
    expect(cellAt('C5')).not.toHaveClass('bg-issue-cell');
    // A rejected finding no longer marks its cell or its row.
    expect(cellAt('B4')).not.toHaveClass('bg-issue-cell');
    expect(cellAt('B4')).not.toHaveTextContent('finding');
    expect(screen.getByRole('rowheader', { name: '4' })).not.toHaveClass('text-violation');
    const markedRow = screen.getByRole('rowheader', { name: '5, has open findings' });
    expect(markedRow).toHaveClass('text-violation');
  });

  it('opens a note on a marked cell whose Review button reviews that finding', async () => {
    mockFetch([{ path: ROWS, respond: rowsPage }]);
    const extra = [1, 2, 3, 4].map((n) => ({
      ...lineTotalIssue,
      issue_id: `iss_extra_${n}`,
      severity: 'low' as const,
      title: `Extra finding ${n}`,
    }));
    const { user, onReview } = renderSheet({ findingsIndex: cellIndex([lineTotalIssue, outlierIssue, ...extra]) });
    await screen.findByRole('grid');

    await user.click(cellAt('A4'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(cellAt('E5'));
    const note = screen.getByRole('dialog', { name: 'Findings for cell E5' });
    expect(within(note).getByText(outlierIssue.title)).toBeInTheDocument();
    expect(within(note).getByText('The unit price lies far outside the prices of comparable items.')).toBeInTheDocument();
    await user.click(within(note).getByRole('button', { name: 'Review' }));
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({ issue_id: 'iss_2' }));

    // Five findings: the three strongest, then a pointer to the Risks tab.
    await user.click(cellAt('F5'));
    const busy = screen.getByRole('dialog', { name: 'Findings for cell F5' });
    expect(within(busy).getAllByRole('button', { name: 'Review' })).toHaveLength(3);
    expect(within(busy).getByText(lineTotalIssue.title)).toBeInTheDocument();
    expect(within(busy).getByText('and 2 more in the Risks tab')).toBeInTheDocument();

    // Escape on the grid closes the note; Close in the note does too and returns to the cell.
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.click(cellAt('E5'));
    const again = screen.getByRole('dialog', { name: 'Findings for cell E5' });
    await user.click(within(again).getByRole('button', { name: 'Close note' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(cellAt('E5')).toHaveFocus();
  });

  it('reveals a cell on another page and opens its note', async () => {
    const all = manyRows(250);
    const api = mockFetch([{ path: ROWS, respond: pagedRows(all) }]);
    const far = {
      ...lineTotalIssue,
      issue_id: 'iss_far',
      row_id: 'row_160',
      affected_cells: [{ table_id: 'tbl_1', row_id: 'row_160', column_id: 'col_text', source: null }],
      title: 'Short text says DN 125, long text says DN 100',
    };
    const { rerender } = renderSheet({ table: { ...table, row_count: 250 }, findingsIndex: cellIndex([far]) });
    await screen.findByRole('rowheader', { name: '4' });

    rerender({ selectedIssue: far, reveal: { tableId: 'tbl_1', rowId: 'row_160', columnId: 'col_text', nonce: 1 } });
    await screen.findByRole('rowheader', { name: /^160/ });
    expect(api.callsTo('GET', ROWS).at(-1)?.query.toString()).toBe('limit=100&row_id=row_160');
    expect(screen.getByRole('navigation', { name: 'rows pages' })).toHaveTextContent('101–200 of 250 rows');
    await waitFor(() => expect(cellBar()).toHaveTextContent('B160'));
    expect(cellAt('B160')).toHaveAttribute('tabindex', '0');
    const note = await screen.findByRole('dialog', { name: 'Findings for cell B160' });
    expect(within(note).getByText(far.title)).toBeInTheDocument();

    // A row on the page is used as it is; without a column the row's first cell is the anchor.
    const calls = api.callsTo('GET', ROWS).length;
    rerender({ selectedIssue: far, reveal: { tableId: 'tbl_1', rowId: 'row_150', columnId: null, nonce: 2 } });
    await waitFor(() => expect(cellBar()).toHaveTextContent('A150'));
    expect(api.callsTo('GET', ROWS)).toHaveLength(calls);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('asks for the page of a revealed row straight away when it opens with one', async () => {
    const api = mockFetch([{ path: ROWS, respond: pagedRows(manyRows(250)) }]);
    const issue = { ...lineTotalIssue, row_id: 'row_230', affected_cells: [{ table_id: 'tbl_1', row_id: 'row_230', column_id: 'col_pos' }] };
    renderSheet({
      table: { ...table, row_count: 250 },
      findingsIndex: cellIndex([issue]),
      selectedIssue: issue,
      reveal: { tableId: 'tbl_1', rowId: 'row_230', columnId: 'col_pos', nonce: 'a' },
    });

    expect(await screen.findByRole('dialog', { name: 'Findings for cell A230' })).toBeInTheDocument();
    expect(api.callsTo('GET', ROWS)).toHaveLength(1);
    expect(api.callsTo('GET', ROWS)[0].query.get('row_id')).toBe('row_230');
    expect(screen.getByRole('navigation', { name: 'rows pages' })).toHaveTextContent('201–250 of 250 rows');
  });

  it('switches to the table of a revealed cell and offers a table picker', async () => {
    mockFetch([{ path: ROWS, respond: rowsPage }]);
    const other = { ...table, table_id: 'tbl_2', name: 'Nachtrag' };
    const { user, onTableChange } = renderSheet({
      tables: [table, other],
      reveal: { tableId: 'tbl_2', rowId: 'row_9', columnId: null, nonce: 1 },
    });
    await screen.findByRole('grid');
    expect(onTableChange).toHaveBeenCalledWith('tbl_2');

    await chooseOption(user, 'Table', /Nachtrag/);
    expect(onTableChange).toHaveBeenLastCalledWith('tbl_2');
  });
});
