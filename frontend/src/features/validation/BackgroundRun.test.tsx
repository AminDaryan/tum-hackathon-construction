import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { errorResponse, jsonResponse, mockFetch, page, type MockResponse, type MockRoute } from '../../test/fetchMock.ts';
import {
  detectorCatalogue,
  documentDetail,
  issueHistory,
  lineTotalIssue,
  outlierIssue,
  riskReport,
  rowsPage,
  runDetail,
  runSummaries,
} from '../../test/fixtures.ts';
import { renderApp } from '../../test/render.tsx';
import type { ValidationRunDetail } from '../../services/apiTypes.ts';
import { projectWorkspaceRoutes, WORKSPACE_URL } from '../../test/workspaceRoutes.ts';

const START = '/api/v1/datasets/ds_1/validation-runs';
const RUN = '/api/v1/validation-runs/run_2';
const ISSUES = `${RUN}/issues`;
const queued: ValidationRunDetail = { ...runDetail, status: 'queued', finished_at: null, detector_reports: [], issue_count: 0 };
const accepted = (run: ValidationRunDetail) => jsonResponse(run, { status: 202, headers: { Location: RUN } });
// A table without a run is checked once it has settled (1.5 s); the first poll comes about a
// second after the start.
const AFTER_START = { timeout: 4000 };
const AFTER_POLL = { timeout: 4000 };

/**
 * The open tender.xlsx. `runs()` is what GET validation-runs lists, `run()` what GET run_2
 * answers (the poll, and the detail of the chosen run). `start` answers each POST with a fresh
 * Response, since a body can be read only once.
 */
function routes({
  runs,
  run,
  start = () => accepted(queued),
}: {
  runs: () => unknown[];
  run: MockResponse;
  start?: MockResponse;
}): MockRoute[] {
  return [
    { path: '/api/v1/documents/doc_1', respond: documentDetail },
    { path: '/api/v1/datasets/ds_1/tables/tbl_1/rows', respond: rowsPage },
    { path: START, respond: () => ({ items: runs() }) },
    { method: 'POST', path: START, respond: start },
    { path: RUN, respond: run },
    { path: ISSUES, respond: page([lineTotalIssue, outlierIssue], { limit: 500 }) },
    { path: '/api/v1/validation-runs/run_2/risks', respond: riskReport },
    { path: '/api/v1/validation-runs/run_2/risk-reviews', respond: { run_id: 'run_2', items: [] } },
    { path: '/api/v1/issues/iss_1', respond: { issue: lineTotalIssue, history: issueHistory } },
    { path: '/api/v1/detectors', respond: detectorCatalogue },
    { path: `${RUN}/problems`, respond: { run_id: 'run_2', total: 0, findings: 0, problems: [] } },
    // The project the file is opened in.
    ...projectWorkspaceRoutes().slice(-3),
  ];
}

async function openWorkspace() {
  const view = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });
  await screen.findByRole('grid', { name: 'Sheet LV' });
  await screen.findByRole('tab', { name: 'Properties' });
  return view;
}

describe('Background validation runs', () => {
  it('checks a table without a run by itself: the live status, then the outcome and the side panel tabs', async () => {
    let finished = false;
    const api = mockFetch(
      routes({
        runs: () => (finished ? runSummaries.slice(0, 1) : []),
        run: () => {
          finished = true;
          return runDetail;
        },
      }),
    );
    const { location } = await openWorkspace();

    // No button: the check starts by itself. The progress and the outcome are for screen readers
    // only; the sheet's header says "Checking…".
    expect(screen.queryByRole('button', { name: /Validat/ })).not.toBeInTheDocument();
    const status = await screen.findByText(/^Validation run queued\./, {}, AFTER_START);
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveClass('sr-only');
    expect(screen.queryByText('Queued')).not.toBeInTheDocument();
    expect(screen.getByText('Checking…')).toBeInTheDocument();
    expect(api.callsTo('POST', START)[0].headers.get('Prefer')).toBe('respond-async');
    // Still running: no result tabs, no findings asked for.
    expect(screen.queryByRole('tab', { name: /^Risks/ })).not.toBeInTheDocument();
    expect(api.callsTo('GET', ISSUES)).toHaveLength(0);

    expect(
      await screen.findByText('Validation run finished with 2 issues. 2 detectors completed, 1 skipped, 1 failed.', {}, AFTER_POLL),
    ).toBe(status);
    expect(status).toHaveClass('sr-only');
    expect(screen.queryByText('Completed with errors')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Show risks' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'View run' })).not.toBeInTheDocument();
    expect(screen.queryByText('Checking…')).not.toBeInTheDocument();

    const risksTab = await screen.findByRole('tab', { name: /^Risks/ });
    await waitFor(() => expect(risksTab).toHaveTextContent('Risks3'));
    expect(risksTab).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(location()).toBe(`${WORKSPACE_URL}&run=run_2`));
    expect(within(await screen.findByRole('list', { name: 'Risks' })).getAllByRole('button')).toHaveLength(3);
    expect(await screen.findByRole('rowheader', { name: '5, has open findings' })).toBeInTheDocument();
    expect(api.callsTo('POST', START)).toHaveLength(1);
  });

  it('reports a background run that failed', async () => {
    const failed = { ...runDetail, status: 'failed', warnings: ['Extraction failed.'], detector_reports: [], issue_count: 0 };
    let done = false;
    const api = mockFetch(
      routes({
        runs: () => (done ? [{ ...runSummaries[0], status: 'failed', issue_count: 0 }] : []),
        start: () => accepted({ ...queued, status: 'running' }),
        run: () => {
          done = true;
          return failed;
        },
      }),
    );
    await openWorkspace();

    expect(await screen.findByText(/^Validation run in progress on the server\./, {}, AFTER_START)).toHaveAttribute('role', 'status');
    expect(screen.queryByText('Running')).not.toBeInTheDocument();

    expect(
      await screen.findByText(
        'The validation run failed before detectors could finish. See the run details for warnings.',
        {},
        AFTER_POLL,
      ),
    ).not.toHaveClass('sr-only');
    // A failed run stays on screen, with its status.
    expect(screen.getByText('Failed')).toBeInTheDocument();
    // The list of runs is loaded again once the run has ended.
    await waitFor(() => expect(api.callsTo('GET', START).length).toBeGreaterThanOrEqual(2));
  });

  it('says when following the run failed, without starting the check again by itself', async () => {
    const api = mockFetch(
      routes({
        runs: () => [],
        run: () => errorResponse(404, 'not_found', "Unknown validation run 'run_2'."),
      }),
    );
    await openWorkspace();

    await screen.findByText(/^Validation run queued\./, {}, AFTER_START);
    const alert = await screen.findByRole('alert', {}, AFTER_POLL);
    expect(within(alert).getByText('The progress of the validation run could not be followed')).toBeInTheDocument();
    expect(within(alert).getByText("Unknown validation run 'run_2'.")).toBeInTheDocument();
    expect(screen.queryByText('Checking…')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /^Risks/ })).not.toBeInTheDocument();
    // The table is unchanged, so no second check follows (no loop).
    await new Promise((resolve) => setTimeout(resolve, 2000));
    expect(api.callsTo('POST', START)).toHaveLength(1);
  });
});
