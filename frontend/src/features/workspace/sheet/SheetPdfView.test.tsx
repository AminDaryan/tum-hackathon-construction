import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { getDocument, type PDFDocumentLoadingTask } from 'pdfjs-dist';
import type { ComponentProps } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../../../test/fetchMock.ts';
import { rowsPage, table } from '../../../test/fixtures.ts';
import { Sheet } from './Sheet.tsx';
import type { PdfSource } from './SheetPdf.tsx';

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: {},
  getDocument: vi.fn(),
  TextLayer: class {
    render() {
      return Promise.resolve();
    }
    cancel() {}
  },
}));

const ROWS = '/api/v1/datasets/ds_1/tables/tbl_1/rows';
const PDF: PdfSource = { documentId: 'doc_1', file: 'LV-Druck.pdf' };
/** The uploaded PDF's bytes; the mocked pdf.js reads none of them. */
const ORIGINAL = { path: '/api/v1/documents/doc_1/original', respond: () => new Response(new Uint8Array([37, 80, 68, 70])) };
const COLUMN_INDEX: Readonly<Record<string, number>> = { A: 0, B: 1, C: 2, E: 3, F: 4 };
/** The fixture table with its position number column mapped as the reader maps an OZ. */
const ozTable = {
  ...table,
  columns: table.columns.map((column) => (column.column_id === 'col_pos' ? { ...column, mapped_semantic_field: 'item_code' } : column)),
};

function item(str: string, x: number, y: number) {
  return { str, transform: [9, 0, 0, 9, x, y], width: str.length * 5, height: 9 };
}

/** Page 1: the section only. Page 2: position 01.001 with its text and quantity. */
const PAGES = [
  [item('01', 60, 760), item('Erdarbeiten', 130, 760)],
  [item('01.001', 60, 700), item('Oberboden abtragen', 130, 700), item('12,500 m3', 320, 680), item('Summe', 60, 600)],
];

function fakePdf() {
  return {
    numPages: PAGES.length,
    getPage: async (number: number) => ({
      view: [0, 0, 595, 842],
      getTextContent: async () => ({ items: PAGES[number - 1] }),
      getViewport: ({ scale }: { scale: number }) => ({
        width: 595 * scale,
        height: 842 * scale,
        convertToViewportPoint: (px: number, py: number) => [px * scale, (842 - py) * scale],
      }),
      render: () => ({ promise: Promise.resolve(), cancel() {} }),
    }),
  };
}

function cellAt(address: string) {
  const match = /^([A-Z]+)(\d+)$/.exec(address);
  if (!match) throw new Error(`${address} is not an A1 address`);
  const [, letter, number] = match;
  const row = within(screen.getByRole('grid'))
    .getAllByRole('row')
    .find((candidate) => within(candidate).queryByRole('rowheader')?.textContent === number);
  if (!row) throw new Error(`Row ${number} is not on the page`);
  return within(row).getAllByRole('gridcell')[COLUMN_INDEX[letter]];
}

function renderSheet(props: Partial<ComponentProps<typeof Sheet>> = {}) {
  const user = userEvent.setup();
  render(<Sheet datasetId="ds_1" table={ozTable} tables={[ozTable]} revision={3} {...props} />);
  return user;
}

beforeEach(() => {
  // Test stand-ins: the fake page never draws, and SheetPdf only reads these of the task and document.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D);
  vi.mocked(getDocument).mockImplementation(
    () => ({ promise: Promise.resolve(fakePdf()), destroy: () => Promise.resolve() }) as unknown as PDFDocumentLoadingTask,
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.mocked(getDocument).mockReset();
});

describe('Sheet PDF view', () => {
  it('has no view switch when the file has no PDF', async () => {
    mockFetch([{ path: ROWS, respond: rowsPage }]);
    renderSheet();
    await screen.findByRole('grid');
    expect(screen.queryByRole('group', { name: 'View' })).not.toBeInTheDocument();
  });

  it('shows the PDF in the same box with the active cell highlighted, and goes back to the table', async () => {
    mockFetch([{ path: ROWS, respond: rowsPage }, ORIGINAL]);
    const user = renderSheet({ pdf: PDF });
    await screen.findByRole('grid');
    const views = screen.getByRole('group', { name: 'View' });
    expect(within(views).getByRole('button', { name: 'Table' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(cellAt('C5'));
    await user.click(within(views).getByRole('button', { name: 'PDF' }));

    expect(screen.queryByRole('grid')).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'rows pages' })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'PDF view: LV-Druck.pdf, the uploaded file' })).toHaveClass(
      'h-[clamp(320px,56dvh,640px)]',
    );
    expect(await screen.findByText('Menge of position 01.001 is highlighted on page 2.')).toHaveAttribute('role', 'status');
    expect(getDocument).toHaveBeenCalledWith({ data: new Uint8Array([37, 80, 68, 70]), isEvalSupported: false });
    expect(await screen.findByTestId('pdf-cell')).toHaveAccessibleName('Cell C5');
    expect(screen.getByTestId('pdf-position')).toHaveAccessibleName('Position 01.001');
    const pages = screen.getByRole('navigation', { name: 'PDF pages' });
    expect(pages).toHaveTextContent('Page 2 of 2');
    expect(screen.getByRole('group', { name: 'Active cell' })).toHaveTextContent('C5');

    await user.click(within(pages).getByRole('button', { name: 'Previous' }));
    expect(await within(pages).findByText('Page 1 of 2')).toBeInTheDocument();
    expect(screen.queryByTestId('pdf-cell')).not.toBeInTheDocument();
    await user.click(within(pages).getByRole('button', { name: 'Back to the cell' }));
    expect(await within(pages).findByText('Page 2 of 2')).toBeInTheDocument();

    await user.click(within(views).getByRole('button', { name: 'Table' }));
    expect(screen.getByRole('grid')).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'rows pages' })).toBeInTheDocument();
  });

  it('marks only the position when the value is not printed, and says when a row cannot be found', async () => {
    mockFetch([{ path: ROWS, respond: rowsPage }, ORIGINAL]);
    const user = renderSheet({ pdf: PDF });
    await screen.findByRole('grid');
    await user.click(cellAt('F5'));
    await user.click(screen.getByRole('button', { name: 'PDF' }));

    expect(await screen.findByText('Position 01.001 is highlighted on page 2. Its Gesamtpreis is not printed there.')).toBeInTheDocument();
    expect(await screen.findByTestId('pdf-position')).toBeInTheDocument();
    expect(screen.queryByTestId('pdf-cell')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Table' }));
    await user.click(cellAt('B6'));
    await user.click(screen.getByRole('button', { name: 'PDF' }));
    expect(await screen.findByText('This row has no position number, so it cannot be found in the PDF.')).toBeInTheDocument();
  });

  it('asks for a cell when none is chosen', async () => {
    mockFetch([{ path: ROWS, respond: rowsPage }, ORIGINAL]);
    const user = renderSheet({ pdf: PDF });
    await screen.findByRole('grid');
    await user.click(screen.getByRole('button', { name: 'PDF' }));
    expect(await screen.findByText('Select a cell in the table to find it in the PDF.')).toBeInTheDocument();
    expect(await screen.findByText('Page 1 of 2')).toBeInTheDocument();
  });

  it('goes back to the table when a risk opens a cell for editing', async () => {
    mockFetch([{ path: ROWS, respond: rowsPage }, ORIGINAL]);
    const user = userEvent.setup();
    const props = { datasetId: 'ds_1', table: ozTable, tables: [ozTable], revision: 3, pdf: PDF };
    const view = render(<Sheet {...props} />);
    await screen.findByRole('grid');
    await user.click(screen.getByRole('button', { name: 'PDF' }));
    expect(screen.queryByRole('grid')).not.toBeInTheDocument();

    view.rerender(<Sheet {...props} reveal={{ tableId: 'tbl_1', rowId: 'row_5', columnId: 'col_qty', edit: true, nonce: 1 }} />);
    expect(await screen.findByRole('textbox', { name: 'Edit C5' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Table' })).toHaveAttribute('aria-pressed', 'true');
  });
});
