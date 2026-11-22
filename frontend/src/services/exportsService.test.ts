import { describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../test/fetchMock.ts';
import { saveBlob } from '../utils/download.ts';
import { downloadDatasetExcel, downloadRunExport, type RunExportKind } from './exportsService.ts';

vi.mock('../utils/download.ts', () => ({ saveBlob: vi.fn() }));

describe('downloadRunExport', () => {
  it.each<[RunExportKind, string]>([
    ['csv', '/api/v1/validation-runs/run_1/export/issues.csv'],
    ['zip', '/api/v1/validation-runs/run_1/export/tables.zip'],
    ['json', '/api/v1/validation-runs/run_1/export/json'],
    ['xlsx', '/api/v1/validation-runs/run_1/export/xlsx'],
  ])('fetches the %s export and saves it under the name the server gives', async (kind, path) => {
    const disposition = { 'Content-Disposition': 'attachment; filename="bill-run_1.out"' };
    mockFetch([{ method: 'GET', path, respond: () => new Response('abc', { headers: disposition }) }]);
    await expect(downloadRunExport('run_1', kind)).resolves.toEqual({ filename: 'bill-run_1.out', size: 3 });
    // Not expect.any(Blob): on Node 22 fetch returns Node's Blob, not jsdom's global Blob.
    const [blob, filename] = vi.mocked(saveBlob).mock.lastCall!;
    expect(await blob.text()).toBe('abc');
    expect(filename).toBe('bill-run_1.out');
  });

  it('falls back to a name with the run id when the server sends none', async () => {
    mockFetch([{ method: 'GET', path: '/api/v1/validation-runs/run_1/export/issues.csv', respond: () => new Response('a') }]);
    await expect(downloadRunExport('run_1', 'csv')).resolves.toEqual({
      filename: 'validation-run-run_1-issues.csv',
      size: 1,
    });
  });
});

describe('downloadDatasetExcel', () => {
  it('fetches the extracted tables as Excel and saves them under the name the server gives', async () => {
    const disposition = { 'Content-Disposition': 'attachment; filename="LV-ds_1-extracted.xlsx"' };
    mockFetch([
      {
        method: 'GET',
        path: '/api/v1/datasets/ds_1/export/xlsx',
        respond: () => new Response('xlsx', { headers: disposition }),
      },
    ]);
    await expect(downloadDatasetExcel('ds_1')).resolves.toEqual({ filename: 'LV-ds_1-extracted.xlsx', size: 4 });
    expect(vi.mocked(saveBlob).mock.lastCall?.[1]).toBe('LV-ds_1-extracted.xlsx');
  });

  it('falls back to a name with the dataset id', async () => {
    mockFetch([{ method: 'GET', path: '/api/v1/datasets/ds_1/export/xlsx', respond: () => new Response('x') }]);
    await expect(downloadDatasetExcel('ds_1')).resolves.toEqual({ filename: 'dataset-ds_1-extracted.xlsx', size: 1 });
  });
});
