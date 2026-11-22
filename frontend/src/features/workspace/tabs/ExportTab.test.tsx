import { render, screen } from '@testing-library/react';
import { chooseOption } from '../../../test/select.ts';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { mockFetch } from '../../../test/fetchMock.ts';
import { runSummaries } from '../../../test/fixtures.ts';
import { saveBlob } from '../../../utils/download.ts';
import { ExportTab } from './ExportTab.tsx';

vi.mock('../../../utils/download.ts', () => ({ saveBlob: vi.fn() }));

const file = (name: string, body: BodyInit) => () => new Response(body, { headers: { 'Content-Disposition': `attachment; filename="${name}"` } });

describe('ExportTab', () => {
  it('downloads the exports of the chosen validation and lets another run be chosen', async () => {
    const api = mockFetch([{ path: '/api/v1/validation-runs/run_2/export/issues.csv', respond: file('issues.csv', 'a;b') }]);
    const onRunChange = vi.fn();
    const user = userEvent.setup();
    render(<ExportTab datasetId="ds_1" runs={runSummaries} runId="run_2" onRunChange={onRunChange} />);

    expect(screen.getByRole('region', { name: 'Validation results' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Download issues (CSV)' }));
    expect(await screen.findByText('Export downloaded: issues.csv (3 B).')).toBeInTheDocument();
    expect(api.callsTo('GET', '/api/v1/validation-runs/run_2/export/issues.csv')).toHaveLength(1);
    expect(vi.mocked(saveBlob).mock.lastCall?.[1]).toBe('issues.csv');

    await chooseOption(user, 'Validation run', (name: string) => !name.includes('(latest)'));
    expect(onRunChange).toHaveBeenCalledWith('run_1');
  });

  it('downloads the table as Excel', async () => {
    const api = mockFetch([{ path: '/api/v1/datasets/ds_1/export/xlsx', respond: file('LV.xlsx', 'xlsx') }]);
    const user = userEvent.setup();
    render(<ExportTab datasetId="ds_1" runs={runSummaries} runId="run_2" onRunChange={() => {}} />);

    await user.click(screen.getByRole('button', { name: 'Download table as Excel' }));

    expect(await screen.findByText('Downloaded LV.xlsx (4 B).')).toBeInTheDocument();
    expect(api.callsTo('GET', '/api/v1/datasets/ds_1/export/xlsx')).toHaveLength(1);
  });

  it('offers only the table without a validation', () => {
    render(<ExportTab datasetId="ds_1" runs={[]} onRunChange={() => {}} />);

    expect(screen.queryByRole('region', { name: 'Validation results' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download table as Excel' })).toBeInTheDocument();
  });
});
