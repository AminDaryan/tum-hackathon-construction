import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../../../test/fetchMock.ts';
import { dataset, documentSummary, table } from '../../../test/fixtures.ts';
import { saveBlob } from '../../../utils/download.ts';
import { formatDateTime } from '../../../utils/format.ts';
import { PropertiesTab } from './PropertiesTab.tsx';
import type { DatasetSummary, DocumentSummary } from '../../../services/apiTypes.ts';

vi.mock('../../../utils/download.ts', () => ({ saveBlob: vi.fn() }));

const gaebDocument: DocumentSummary = {
  ...documentSummary,
  original_filename: 'Pumpwerk.D86',
  format: 'gaeb_d86',
  size_bytes: 20480,
};

const gaebDataset: DatasetSummary = {
  ...dataset,
  extraction: {
    adapter_id: 'gaeb.gaeb90',
    adapter_version: '1.0.0',
    quality: 'needs_review',
    warnings: [
      {
        code: 'gaeb90_invalid_item_number',
        message: 'An item number does not fit the OZ mask and is kept as written.',
        table_id: 'tbl_1',
        source: null,
        count: 2,
        needs_review: true,
      },
    ],
    details: {
      gaeb_version: '90',
      gaeb_phase: '86',
      gaeb_dp: '86',
      gaeb_schema: null,
      gaeb_schema_sha256: null,
      gaeb_boq_id: 'LV-12',
      project: 'Neubau Pumpwerk',
      currency: 'EUR',
      encoding: 'cp850',
      price_components_not_shown: 3,
    },
  },
};

/** The value of a fact in a section's key-value list. */
function fact(region: HTMLElement, label: string) {
  return within(region).getByText(label, { selector: 'dt' }).nextElementSibling!.textContent;
}

describe('PropertiesTab', () => {
  it('shows the file summary open and the GAEB facts and technical details on demand', async () => {
    const user = userEvent.setup();
    render(<PropertiesTab document={gaebDocument} dataset={gaebDataset} onModelChanged={vi.fn()} />);

    expect(screen.queryByRole('region', { name: 'GAEB' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'GAEB' }));
    const gaeb = screen.getByRole('region', { name: 'GAEB' });
    expect(fact(gaeb, 'Format')).toBe('GAEB 90');
    expect(fact(gaeb, 'Exchange phase')).toBe('86 Auftragserteilung (contract award)');
    expect(fact(gaeb, 'Project')).toBe('Neubau Pumpwerk');
    expect(fact(gaeb, 'Bill of quantities id')).toBe('LV-12');
    expect(fact(gaeb, 'Currency')).toBe('EUR');
    expect(fact(gaeb, 'Text encoding')).toBe('cp850');
    // Any other key the reader reported is listed under its humanized name.
    expect(fact(gaeb, 'Price components not shown')).toBe('3');
    // The data phase says nothing more than the phase here.
    expect(within(gaeb).queryByText('Data phase (DP)')).not.toBeInTheDocument();

    const file = screen.getByRole('region', { name: 'File' });
    expect(fact(file, 'Name')).toBe('Pumpwerk.D86');
    expect(fact(file, 'Format')).toBe('GAEB 90 D86');
    expect(fact(file, 'Size')).toBe('20.0 KB');
    expect(fact(file, 'Uploaded')).toBe(formatDateTime(documentSummary.uploaded_at));
    expect(fact(file, 'Reading quality')).toBe('Needs review');
    await user.click(screen.getByRole('button', { name: 'Technical details' }));
    const details = screen.getByRole('region', { name: 'Technical details' });
    expect(fact(details, 'SHA-256')).toBe(documentSummary.sha256);
    expect(fact(details, 'Profile')).toBe('boq 1.0.0');
    expect(fact(details, 'Read by')).toBe('gaeb.gaeb90 1.0.0');
  });

  it('shows no GAEB facts for an Excel file, and lists how it was read under Technical details', async () => {
    const user = userEvent.setup();
    const excel = { ...dataset, extraction: { ...dataset.extraction, details: { worksheets: 2, formula_cells: 14 } } };
    render(<PropertiesTab document={documentSummary} dataset={excel} onModelChanged={vi.fn()} />);

    expect(screen.queryByRole('region', { name: 'GAEB' })).not.toBeInTheDocument();
    expect(screen.queryByText('Exchange phase')).not.toBeInTheDocument();
    expect(fact(screen.getByRole('region', { name: 'File' }), 'Format')).toBe('XLSX');
    await user.click(screen.getByRole('button', { name: 'Technical details' }));
    const details = screen.getByRole('region', { name: 'Technical details' });
    expect(fact(details, 'Worksheets')).toBe('2');
    expect(fact(details, 'Formula cells')).toBe('14');
  });

  it('has no part for the tables and their columns, nor for the notes from reading the file', () => {
    const second = { ...table, table_id: 'tbl_2', name: 'Anhang' };
    render(<PropertiesTab document={gaebDocument} dataset={{ ...gaebDataset, tables: [table, second] }} onModelChanged={vi.fn()} />);

    expect(screen.getByRole('button', { name: 'Technical details' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Table/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    // The bill has a note from reading it, which the tab does not list.
    expect(screen.queryByRole('button', { name: /^Notes from reading the file/ })).not.toBeInTheDocument();
    expect(screen.queryByText('An item number does not fit the OZ mask and is kept as written.')).not.toBeInTheDocument();
  });

  it('downloads the table as Excel', async () => {
    const api = mockFetch([
      {
        path: '/api/v1/datasets/ds_1/export/xlsx',
        respond: () => new Response('xlsx', { headers: { 'Content-Disposition': 'attachment; filename="LV.xlsx"' } }),
      },
    ]);
    const user = userEvent.setup();
    render(<PropertiesTab document={documentSummary} dataset={dataset} onModelChanged={vi.fn()} />);

    await user.click(screen.getByRole('button', { name: 'Download table as Excel' }));

    expect(await screen.findByText('Downloaded LV.xlsx (4 B).')).toBeInTheDocument();
    expect(api.callsTo('GET', '/api/v1/datasets/ds_1/export/xlsx')).toHaveLength(1);
    expect(vi.mocked(saveBlob).mock.lastCall?.[1]).toBe('LV.xlsx');
  });

  it('attaches a design model, shows what it links and removes it', async () => {
    const model = {
      filename: 'design.ifc',
      sha256: 'a'.repeat(64),
      size_bytes: 1200,
      schema_name: 'IFC4X3_ADD2',
      project: 'Ringschluss',
      elements: 462,
      unlinked_elements: 3,
      linked_positions: 115,
    };
    const path = `/api/v1/documents/${documentSummary.document_id}/model`;
    const api = mockFetch([
      { method: 'PUT', path, respond: () => ({ document: { ...documentSummary, model } }) },
      { method: 'DELETE', path, respond: () => ({ document: { ...documentSummary, model: null } }) },
    ]);
    const onModelChanged = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<PropertiesTab document={documentSummary} dataset={dataset} onModelChanged={onModelChanged} />);

    const section = screen.getByRole('region', { name: 'Design model (IFC)' });
    // The state alone, with no explanation under the title.
    expect(within(section).getByText('No model attached')).toBeInTheDocument();
    expect(within(section).queryByText(/checked against the bill/)).not.toBeInTheDocument();
    await user.upload(within(section).getByLabelText('Choose an IFC model to attach'), new File(['ISO-10303-21;'], 'design.ifc'));
    await vi.waitFor(() => expect(onModelChanged).toHaveBeenCalledTimes(1));
    expect(api.callsTo('PUT', path)[0].body.get('file').name).toBe('design.ifc');

    // The workspace reloads the file, which now carries the model.
    rerender(<PropertiesTab document={{ ...documentSummary, model }} dataset={dataset} onModelChanged={onModelChanged} />);
    expect(fact(section, 'File')).toBe('design.ifc');
    expect(fact(section, 'Linked item numbers')).toBe('115');
    expect(fact(section, 'Elements without an item number')).toBe('3');

    await user.click(within(section).getByRole('button', { name: 'Remove' }));
    await vi.waitFor(() => expect(onModelChanged).toHaveBeenCalledTimes(2));
    expect(api.callsTo('DELETE', path)).toHaveLength(1);
  });
});
