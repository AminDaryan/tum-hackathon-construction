import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { errorResponse, mockFetch } from '../../test/fetchMock.ts';
import { documentSummary } from '../../test/fixtures.ts';
import { renderApp } from '../../test/render.tsx';
import { chooseOption, getSelect } from '../../test/select.ts';
import { WORKSPACE_PROJECT } from '../../test/workspaceRoutes.ts';
import { saveBlob } from '../../utils/download.ts';
import type { Project } from '../../services/apiTypes.ts';
import type { ProjectReport } from '../../services/projectsService.ts';

vi.mock('../../utils/download.ts', () => ({ saveBlob: vi.fn() }));

const file = (name: string, body: string) => () => new Response(body, { headers: { 'Content-Disposition': `attachment; filename="${name}"` } });
const validated: Project = {
  ...WORKSPACE_PROJECT,
  validation: { status: 'completed', started_at: '2026-11-21T12:00:00Z', finished_at: '2026-11-21T12:01:00Z', runs: { doc_1: 'run_2' }, skipped: {}, comparisons: [], error: null },
};
const detail = (project: Project) => ({ path: '/api/v1/projects/prj_1', respond: { project, documents: [documentSummary], review_counts: {} } });
const REPORTS = '/api/v1/projects/prj_1/reports';

function report(id: string, overrides: Partial<ProjectReport> = {}) {
  return {
    report_id: id,
    created_at: '2026-11-21T12:05:00Z',
    format: 'pdf',
    document_id: null,
    filename: 'Riverside-project-report.pdf',
    media_type: 'application/pdf',
    size_bytes: 4,
    storage_key: 'a'.repeat(64),
    validated_at: '2026-11-21T12:01:00Z',
    ...overrides,
  };
}
describe('Reports of a project', () => {
  it('generates a report on the whole project or on one bill, keeps it in the table and downloads it', async () => {
    let kept: ReturnType<typeof report>[] = [];
    const created: { format: string; document_id: string | null }[] = [];
    const api = mockFetch([
      detail(validated),
      { path: REPORTS, respond: () => ({ items: [...kept].reverse() }) },
      {
        method: 'POST',
        path: REPORTS,
        respond: (call) => {
          const body = JSON.parse(call.body);
          created.push(body);
          const next =
            body.document_id === null
              ? report('rpt_1')
              : report('rpt_2', { format: body.format, document_id: body.document_id, filename: 'tender-run_2.xlsx' });
          kept = [...kept, next];
          return next;
        },
      },
      { path: `${REPORTS}/rpt_1/file`, respond: file('Riverside-project-report.pdf', '%PDF') },
      { path: `${REPORTS}/rpt_2/file`, respond: file('tender-run_2.xlsx', 'PK') },
    ]);
    const { user } = renderApp('/projects/prj_1/reports');

    expect(await screen.findByRole('heading', { level: 1, name: 'Reports' })).toBeInTheDocument();
    const table = await screen.findByRole('region', { name: /^Reports/ });
    expect(await within(table).findByText('No reports yet')).toBeInTheDocument();

    const card = screen.getByRole('region', { name: 'Generate a report' });
    // Only the bid risk report opens on screen.
    expect(within(card).queryByRole('link', { name: 'View on screen' })).not.toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: 'Generate report' }));
    await waitFor(() => expect(vi.mocked(saveBlob).mock.lastCall?.[1]).toBe('Riverside-project-report.pdf'));
    expect(created).toEqual([{ format: 'pdf', document_id: null }]);
    const rows = () => within(within(table).getByRole('table', { name: 'Reports' })).getAllByRole('row').slice(1);
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(rows()[0]).toHaveTextContent('Riverside-project-report.pdfWhole projectPDF report');
    await chooseOption(user, 'Report on', 'tender.xlsx', card);
    await chooseOption(user, 'Type', 'Excel workbook', card);
    await user.click(within(card).getByRole('button', { name: 'Generate report' }));
    await waitFor(() => expect(vi.mocked(saveBlob).mock.lastCall?.[1]).toBe('tender-run_2.xlsx'));
    expect(created[1]).toEqual({ format: 'xlsx', document_id: 'doc_1' });
    // Newest first.
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(rows()[0]).toHaveTextContent('tender-run_2.xlsxtender.xlsxExcel workbook');

    // A kept report downloads again.
    await user.click(within(rows()[1]).getByRole('button', { name: 'Download Riverside-project-report.pdf' }));
    await waitFor(() => expect(api.callsTo('GET', `${REPORTS}/rpt_1/file`)).toHaveLength(2));
  });

  it('generates the bid risk report of the whole project as one of the report types', async () => {
    const created: { format: string; document_id: string | null }[] = [];
    mockFetch([
      detail(validated),
      { path: REPORTS, respond: { items: [] } },
      {
        method: 'POST',
        path: REPORTS,
        respond: (call) => {
          created.push(JSON.parse(call.body));
          return report('rpt_3', { format: 'bid-risk.pdf', filename: 'Riverside-bid-risk-report.pdf' });
        },
      },
      { path: `${REPORTS}/rpt_3/file`, respond: file('Riverside-bid-risk-report.pdf', '%PDF') },
      { path: '/api/v1/projects/prj_1/risk-report', respond: errorResponse(409, 'conflict', 'A validation is running.') },
    ]);
    const { user, location } = renderApp('/projects/prj_1/reports');
    const card = await screen.findByRole('region', { name: 'Generate a report' });
    // The page is laid out while the project loads; its controls work once it is there.
    await waitFor(() => expect(getSelect('Report on', card)).toBeEnabled());
    await chooseOption(user, 'Report on', 'tender.xlsx', card);
    await chooseOption(user, 'Type', 'Bid risk report (PDF)', card);
    // It covers the whole project, whatever bill was chosen.
    expect(getSelect('Report on', card)).toHaveTextContent('Whole project');
    expect(getSelect('Report on', card)).toBeDisabled();
    await user.click(within(card).getByRole('button', { name: 'Generate report' }));
    await waitFor(() => expect(vi.mocked(saveBlob).mock.lastCall?.[1]).toBe('Riverside-bid-risk-report.pdf'));
    expect(created).toEqual([{ format: 'bid-risk.pdf', document_id: null }]);

    // It also opens on screen, and leads back to the reports.
    await user.click(within(card).getByRole('link', { name: 'View on screen' }));
    expect(location()).toBe('/projects/prj_1/report');
    await user.click(await screen.findByRole('button', { name: 'Back to reports' }));
    expect(location()).toBe('/projects/prj_1/reports');
  });

  it('after a validation that stopped part-way, offers the bid risk report only', async () => {
    const created: unknown[] = [];
    const stopped: Project = { ...validated, validation: { ...validated.validation!, status: 'failed', error: 'The server stopped.' } };
    mockFetch([
      detail(stopped),
      { path: REPORTS, respond: { items: [] } },
      {
        method: 'POST',
        path: REPORTS,
        respond: (call) => {
          created.push(JSON.parse(call.body));
          return report('rpt_3', { format: 'bid-risk.pdf', filename: 'Riverside-bid-risk-report.pdf' });
        },
      },
      { path: `${REPORTS}/rpt_3/file`, respond: file('Riverside-bid-risk-report.pdf', '%PDF') },
    ]);
    const { user } = renderApp('/projects/prj_1/reports');
    const card = await screen.findByRole('region', { name: 'Generate a report' });
    await waitFor(() => expect(getSelect('Type', card)).toHaveTextContent('Bid risk report (PDF)'));
    expect(getSelect('Report on', card)).toBeDisabled();
    await user.click(getSelect('Type', card));
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual(['Bid risk report (PDF)']);
    await user.keyboard('{Escape}');
    await user.click(within(card).getByRole('button', { name: 'Generate report' }));
    await waitFor(() => expect(vi.mocked(saveBlob).mock.lastCall?.[1]).toBe('Riverside-bid-risk-report.pdf'));
    expect(created).toEqual([{ format: 'bid-risk.pdf', document_id: null }]);
  });

  it('asks for a validation first and still shows the reports kept', async () => {
    mockFetch([detail(WORKSPACE_PROJECT), { path: REPORTS, respond: { items: [report('rpt_1')] } }]);
    renderApp('/projects/prj_1/reports');
    expect(await screen.findByText('Validate the project first.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Generate report' })).not.toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Download Riverside-project-report.pdf' })).toBeInTheDocument();
  });
});
