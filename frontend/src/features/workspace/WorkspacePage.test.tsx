import { act, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ACTIVE_DOCUMENT_STORAGE_KEY } from '../../stores/activeDocumentStorage.ts';
import { errorResponse, jsonResponse, mockFetch, type MockCall } from '../../test/fetchMock.ts';
import { findProjectNav } from '../../test/navigation.ts';
import {
  dataset,
  documentDetail,
  documentSummary,
  issueHistory,
  lineTotalIssue,
  riskReport,
  rows,
  runDetail,
  runSummaries,
} from '../../test/fixtures.ts';
import { renderApp } from '../../test/render.tsx';
import { ISSUES, projectWorkspaceRoutes, ROWS, RUNS, WORKSPACE_URL } from '../../test/workspaceRoutes.ts';

/** Rows with source numbers 4, 5, ... for paging. */
function manyRows(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    ...rows[1],
    row_id: `row_${index + 4}`,
    position: index,
    source_row_number: index + 4,
  }));
}

function pagedRows(all: unknown[]) {
  return (call: MockCall) => {
    const offset = Number(call.query.get('offset') ?? 0);
    const limit = Number(call.query.get('limit'));
    return { items: all.slice(offset, offset + limit), total: all.length, offset, limit };
  };
}

/** The Risks tab, once its count of risks to review reads `count`. */
async function risksTabWithCount(count: number | string) {
  const tab = await screen.findByRole('tab', { name: /^Risks/ });
  await waitFor(() => expect(tab).toHaveTextContent(`Risks${count}`));
  return tab;
}

function tabNames() {
  return within(screen.getByRole('tablist', { name: 'Side panel' }))
    .getAllByRole('tab')
    .map((tab) => tab.textContent);
}

/** The grid cell at an A1 address of the fixture table (columns A, B, C, E, F). */
function cellAt(address: string) {
  const columns: Record<string, number> = { A: 0, B: 1, C: 2, E: 3, F: 4 };
  const match = /^([A-Z]+)(\d+)$/.exec(address);
  if (!match) throw new Error(`${address} is not an A1 address`);
  const [, letter, number] = match;
  const row = within(screen.getByRole('grid'))
    .getAllByRole('row')
    .find((candidate) => new RegExp(`^${number}(,|$)`).test(within(candidate).queryByRole('rowheader')?.textContent ?? ''));
  if (!row) throw new Error(`Row ${number} is not on the page`);
  return within(row).getAllByRole('gridcell')[columns[letter]];
}

function deferred() {
  // Set by the promise's executor, which runs at once.
  let resolve!: () => void;
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('Workspace', () => {
  it('forgets a missing remembered file and goes to Projects, including after remount', async () => {
    const api = mockFetch([
      { path: '/api/v1/documents/doc_gone', respond: errorResponse(404, 'not_found', 'Unknown document.') },
      { path: '/api/v1/projects', respond: [] },
    ]);
    const { unmount, location } = renderApp('/workspace', { activeDocumentId: 'doc_gone' });

    expect(await screen.findByText('No projects yet')).toBeInTheDocument();
    expect(location()).toBe('/projects');
    expect(window.localStorage.getItem(ACTIVE_DOCUMENT_STORAGE_KEY)).toBeNull();
    expect(screen.queryByText('This file is no longer available')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    unmount();
    renderApp('/workspace');
    expect(await screen.findByText('No projects yet')).toBeInTheDocument();
    expect(api.callsTo('GET', '/api/v1/documents/doc_gone')).toHaveLength(1);
  });

  it('keeps the remembered file retryable when the server fails rather than reporting it missing', async () => {
    mockFetch(projectWorkspaceRoutes({ extra: [{ path: '/api/v1/documents/doc_1', respond: errorResponse(500, 'internal_error', 'Try again later.') }] }));
    renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });

    expect(await screen.findByRole('alert')).toHaveTextContent('The file could not be loaded');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
    expect(window.localStorage.getItem(ACTIVE_DOCUMENT_STORAGE_KEY)).toBe('doc_1');
  });

  it('shows the open file: its name after its project\'s, the sheet and the side panel with Properties before a run', async () => {
    const api = mockFetch(projectWorkspaceRoutes());
    renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });

    const topBar = within(await screen.findByRole('banner', { name: 'Top bar' }));
    expect(await topBar.findByRole('heading', { level: 1, name: 'tender.xlsx' })).toBeInTheDocument();
    // "Riverside / tender.xlsx", like a breadcrumb: the project's name leads to the project, and
    // there is no back button.
    const project = await topBar.findByRole('link', { name: 'Riverside' });
    expect(project).toHaveAttribute('href', '/projects/prj_1');
    expect(project.compareDocumentPosition(topBar.getByRole('heading', { level: 1 })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(topBar.queryByRole('button', { name: /^Back/ })).not.toBeInTheDocument();
    const grid = await screen.findByRole('grid', { name: 'Sheet LV' });
    expect(within(grid).getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['4', '5', '6']);
    expect(cellAt('B5')).toHaveTextContent('Oberboden abtragen');
    // The table is checked by itself, so there is no button to validate it.
    expect(screen.queryByRole('button', { name: /Validat/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Choose checks' })).not.toBeInTheDocument();

    await waitFor(() => expect(api.callsTo('GET', RUNS)).not.toHaveLength(0));
    expect(screen.getByRole('complementary', { name: 'Side panel' })).toBeInTheDocument();
    // tender.xlsx has no linked 3D model, so there is no tab for one.
    expect(tabNames()).toEqual(['Properties', 'What-if', 'Quantities']);
    // Before a run Properties opens first.
    expect(screen.getByRole('tab', { name: 'Properties' })).toHaveAttribute('aria-selected', 'true');
    expect(within(screen.getByRole('tabpanel')).getByRole('heading', { name: 'File' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /Risks/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Extraction needs review')).not.toBeInTheDocument();
    expect(api.callsTo('GET', ISSUES)).toHaveLength(0);
  });

  it('hides the side panel so the sheet takes the full width, and shows it again when a risk opens', async () => {
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries }));
    const { user, location } = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });
    await risksTabWithCount(3);
    await screen.findByRole('rowheader', { name: '5, has open findings' });

    const hide = screen.getByRole('button', { name: 'Hide the side panel' });
    expect(hide).toHaveAttribute('aria-expanded', 'true');
    await user.click(hide);
    expect(screen.queryByRole('complementary', { name: 'Side panel' })).not.toBeInTheDocument();
    expect(screen.queryByRole('separator', { name: 'Width of the side panel' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show the side panel' })).toHaveAttribute('aria-expanded', 'false');

    // Without the panel a flagged cell opens its note in the sheet; Review opens the risk in the panel.
    await user.click(cellAt('F5'));
    const note = await screen.findByRole('dialog', { name: 'Findings for cell F5' });
    await user.click(within(note).getAllByRole('button', { name: 'Review' })[0]);
    expect(await screen.findByRole('complementary', { name: 'Side panel' })).toBeInTheDocument();
    await waitFor(() => expect(location()).toContain('risk=risk_total'));
    expect(screen.getByRole('button', { name: 'Hide the side panel' })).toBeInTheDocument();
  });

  it('shows the sheet full screen, the rest inert, until Exit or the browser leaves full screen', async () => {
    mockFetch(projectWorkspaceRoutes());
    let fullscreenElement: Element | null = null;
    const requestFullscreen = vi.fn(() => {
      fullscreenElement = document.documentElement;
      return Promise.resolve();
    });
    const exitFullscreen = vi.fn(() => {
      fullscreenElement = null;
      return Promise.resolve();
    });
    Object.defineProperty(document, 'fullscreenEnabled', { configurable: true, get: () => true });
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => fullscreenElement });
    document.exitFullscreen = exitFullscreen;
    document.documentElement.requestFullscreen = requestFullscreen;
    try {
      const { user } = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });
      const grid = await screen.findByRole('grid', { name: 'Sheet LV' });
      const panel = screen.getByRole('complementary', { name: 'Side panel' });
      const topBar = screen.getByRole('banner', { name: 'Top bar' });
      const projectBar = screen.getByRole('navigation', { name: 'Project' });

      await user.click(screen.getByRole('button', { name: 'Full screen' }));
      expect(requestFullscreen).toHaveBeenCalledTimes(1);
      expect(grid.closest('section')).toHaveClass('fixed', 'inset-0');
      expect(grid.closest('[inert]')).toBeNull();
      expect(panel.closest('[inert]')).not.toBeNull();
      expect(topBar.closest('[inert]')).not.toBeNull();
      expect(projectBar.closest('[inert]')).not.toBeNull();

      await user.click(screen.getByRole('button', { name: 'Exit full screen' }));
      expect(exitFullscreen).toHaveBeenCalledTimes(1);
      expect(grid.closest('section')).not.toHaveClass('fixed');
      expect(panel.closest('[inert]')).toBeNull();
      expect(topBar.closest('[inert]')).toBeNull();
      expect(projectBar.closest('[inert]')).toBeNull();

      // Escape leaves the browser's full screen; the sheet follows.
      await user.click(screen.getByRole('button', { name: 'Full screen' }));
      act(() => {
        fullscreenElement = null;
        document.dispatchEvent(new Event('fullscreenchange'));
      });
      expect(screen.getByRole('button', { name: 'Full screen' })).toBeInTheDocument();
      expect(panel.closest('[inert]')).toBeNull();
    } finally {
      // Remove the test's own properties, so later tests see jsdom's document again.
      const testDocument = document as Partial<Record<'fullscreenEnabled' | 'fullscreenElement' | 'exitFullscreen', unknown>>;
      delete testDocument.fullscreenEnabled;
      delete testDocument.fullscreenElement;
      delete testDocument.exitFullscreen;
      delete (document.documentElement as Partial<Pick<HTMLElement, 'requestFullscreen'>>).requestFullscreen;
    }
  });

  it('shows the sheet full screen without the browser API, filling the window', async () => {
    mockFetch(projectWorkspaceRoutes());
    const { user } = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });
    const grid = await screen.findByRole('grid', { name: 'Sheet LV' });
    await user.click(screen.getByRole('button', { name: 'Full screen' }));
    expect(grid.closest('section')).toHaveClass('fixed');
    await user.click(screen.getByRole('button', { name: 'Exit full screen' }));
    expect(grid.closest('section')).not.toHaveClass('fixed');
  });

  it('grows the sheet to the window and back in a view transition, and switches at once with reduced motion', async () => {
    mockFetch(projectWorkspaceRoutes());
    // Each change of full screen runs inside the transition: what it showed before and after.
    const changes: string[] = [];
    const shownButton = () => (screen.queryByRole('button', { name: 'Exit full screen' }) ? 'full screen' : 'in the page');
    const startViewTransition = vi.fn((update: () => void) => {
      const before = shownButton();
      update();
      changes.push(`${before} -> ${shownButton()}`);
      return { ready: Promise.resolve(), finished: Promise.resolve(), updateCallbackDone: Promise.resolve(), skipTransition: () => {} };
    });
    Object.defineProperty(document, 'startViewTransition', { configurable: true, value: startViewTransition });
    try {
      const { user } = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });
      await screen.findByRole('grid', { name: 'Sheet LV' });

      await user.click(screen.getByRole('button', { name: 'Full screen' }));
      await user.click(screen.getByRole('button', { name: 'Exit full screen' }));
      expect(changes).toEqual(['in the page -> full screen', 'full screen -> in the page']);

      document.documentElement.dataset.motion = 'reduce';
      await user.click(screen.getByRole('button', { name: 'Full screen' }));
      expect(screen.getByRole('button', { name: 'Exit full screen' })).toBeInTheDocument();
      expect(startViewTransition).toHaveBeenCalledTimes(2);
    } finally {
      delete document.documentElement.dataset.motion;
      delete (document as Partial<Pick<Document, 'startViewTransition'>>).startViewTransition;
    }
  });

  it('pages through the rows 100 at a time and keeps one page in the DOM', async () => {
    const api = mockFetch(projectWorkspaceRoutes({ rowsRespond: pagedRows(manyRows(250)) }));
    const { user } = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });

    await screen.findByRole('rowheader', { name: '4' });
    expect(screen.getAllByRole('rowheader')).toHaveLength(100);
    expect(screen.getByRole('navigation', { name: 'rows pages' })).toHaveTextContent('1–100 of 250 rows');
    expect(api.callsTo('GET', ROWS)[0].query.toString()).toBe('offset=0&limit=100');

    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByRole('rowheader', { name: '104' });
    expect(screen.queryByRole('rowheader', { name: '4' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('rowheader')).toHaveLength(100);
    expect(screen.getByRole('navigation', { name: 'rows pages' })).toHaveTextContent('101–200 of 250 rows');
    expect(api.callsTo('GET', ROWS).at(-1)?.query.toString()).toBe('offset=100&limit=100');
  });

  it('shows the side panel tabs of a finished run, the count to review and the marked cells', async () => {
    const api = mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries }));
    const { user, location } = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });

    // With a finished run Risks opens first; the red pill counts the open risks.
    const risksTab = await risksTabWithCount(3);
    expect(tabNames()).toEqual(['Properties', 'Risks3', 'What-if', 'Quantities']);
    expect(risksTab).toHaveAttribute('aria-selected', 'true');
    expect(within(risksTab).getByText('3')).toHaveClass('bg-violation');
    const list = await screen.findByRole('list', { name: 'Risks' });
    expect(within(list).getAllByRole('button').map((row) => row.dataset.riskId)).toEqual(riskReport.risks.map((risk) => risk.risk_id));
    expect(api.callsTo('GET', ISSUES)[0].query.toString()).toBe('offset=0&limit=500');
    expect(api.callsTo('GET', '/api/v1/validation-runs/run_1/issues')).toHaveLength(0);

    // The cells the findings concern are washed red and say so; the input-only quantity is not.
    await screen.findByRole('rowheader', { name: '5, has open findings' });
    expect(cellAt('F5')).toHaveClass('bg-issue-cell');
    expect(cellAt('F5')).toHaveTextContent(', 1 finding');
    expect(cellAt('E5')).toHaveClass('bg-issue-cell');
    expect(cellAt('C5')).not.toHaveClass('bg-issue-cell');
    expect(screen.getByRole('rowheader', { name: '4' })).not.toHaveClass('text-violation');

    // A flagged cell opens its risk in the panel; no note repeats it on the sheet.
    await user.click(cellAt('F5'));
    await waitFor(() => expect(location()).toContain('risk=risk_total'));
    expect(screen.queryByRole('dialog', { name: 'Findings for cell F5' })).not.toBeInTheDocument();

    // Nothing above the table: no picker of the table's runs and no "Validation of" line.
    expect(screen.queryByRole('button', { name: /Validation run/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/^Validation of /)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Next best action' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Your next priorities' })).not.toBeInTheDocument();
  });

  it('opens a file linked to its Risks tab on Risks while its runs still load', async () => {
    const listed = deferred();
    mockFetch(
      projectWorkspaceRoutes({
        extra: [
          {
            method: 'GET',
            path: RUNS,
            respond: async () => {
              await listed.promise;
              return { items: runSummaries };
            },
          },
        ],
      }),
    );
    renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });

    await screen.findByRole('grid', { name: 'Sheet LV' });
    expect(screen.getByRole('tab', { name: /^Risks/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Properties' })).toHaveAttribute('aria-selected', 'false');
    expect(within(screen.getByRole('tabpanel')).queryByRole('heading', { name: 'File' })).not.toBeInTheDocument();

    listed.resolve();
    expect(await risksTabWithCount(3)).toHaveAttribute('aria-selected', 'true');
  });

  it('checks a table without a run by itself once it has settled, then opens Risks', async () => {
    const started = deferred();
    let runs: typeof runSummaries = [];
    const api = mockFetch(
      projectWorkspaceRoutes({
        runs: () => runs,
        extra: [
          {
            method: 'POST',
            path: RUNS,
            respond: async () => {
              await started.promise;
              runs = runSummaries.slice(0, 1);
              return jsonResponse(runDetail, { status: 201 });
            },
          },
        ],
      }),
    );
    const { location } = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });
    await screen.findByRole('grid', { name: 'Sheet LV' });
    await waitFor(() => expect(api.callsTo('GET', RUNS)).toHaveLength(1));
    expect(api.callsTo('POST', RUNS)).toHaveLength(0); // not before the delay

    expect(await screen.findByText('Checking…', {}, { timeout: 3000 })).toBeInTheDocument();
    const [post] = api.callsTo('POST', RUNS);
    expect(JSON.parse(post.body)).toEqual({});
    expect(post.headers.get('Prefer')).toBe('respond-async');
    expect(api.callsTo('GET', ISSUES)).toHaveLength(0);

    started.resolve();
    expect(
      await screen.findByText('Validation run finished with 2 issues. 2 detectors completed, 1 skipped, 1 failed.'),
    ).toHaveClass('sr-only');
    expect(screen.queryByRole('link', { name: 'Show risks' })).not.toBeInTheDocument();
    const risksTab = await risksTabWithCount(3);
    expect(risksTab).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(location()).toBe(`${WORKSPACE_URL}&run=run_2`));
    expect(await screen.findByRole('list', { name: 'Risks' })).toBeInTheDocument();
    expect(screen.queryByText(/^Validation of /)).not.toBeInTheDocument();
    expect(api.callsTo('GET', ISSUES)).not.toHaveLength(0);
    expect(screen.queryByText('Checking…')).not.toBeInTheDocument();
    expect(api.callsTo('POST', RUNS)).toHaveLength(1);
  });

  it('opens a risk from the Risks list, and Approve records the decision on its finding', async () => {
    const approved = {
      ...lineTotalIssue,
      review_status: 'confirmed_error',
      version: 2,
      reviewed_at: '2026-11-21T12:05:00Z',
      allowed_review_actions: ['pending_review', 'false_positive', 'needs_more_information'],
    };
    const api = mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [{ method: 'POST', path: '/api/v1/issues/iss_1/review', respond: { issue: approved, history: issueHistory } }],
      }),
    );
    const { user, location } = renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });

    const list = await screen.findByRole('list', { name: 'Risks' });
    expect(within(list).getAllByRole('button')).toHaveLength(3);
    await user.click(within(list).getByRole('button', { name: /Arithmetic/ }));

    await waitFor(() => expect(location()).toContain('risk=risk_total'));
    const panel = screen.getByRole('complementary', { name: 'Side panel' });
    expect(within(panel).getByText('Risk 1 of 3')).toBeInTheDocument();
    expect(within(panel).getByRole('heading', { name: 'Arithmetic', level: 2 })).toBeInTheDocument();
    expect(within(panel).getByText(riskReport.risks[0].title)).toBeInTheDocument();
    const group = within(panel).getByRole('group', { name: 'Review decision' });
    expect(within(group).getByRole('button', { name: /^Reject/ })).toBeInTheDocument();
    expect(within(group).getByRole('button', { name: 'Needs clarification' })).toBeInTheDocument();
    // the shown finding's cell is ringed in the sheet
    expect(cellAt('F5')).toHaveClass('bg-issue-cell-strong');

    await user.click(within(group).getByRole('button', { name: /^Approve/ }));
    expect(await within(group).findByText(/^Approved on /)).toBeInTheDocument();
    const posts = api.callsTo('POST', '/api/v1/issues/iss_1/review');
    expect(posts).toHaveLength(1);
    expect(JSON.parse(posts[0].body)).toEqual({ status: 'confirmed_error', expected_version: 1 });
    // The decision bar offers the next risk to review; the report is read again.
    expect(within(group).getByRole('button', { name: 'Next risk' })).toBeInTheDocument();
    await waitFor(() => expect(api.callsTo('GET', '/api/v1/validation-runs/run_2/risks').length).toBeGreaterThan(1));
    expect(screen.getByRole('tab', { name: /^Risks/ })).toHaveTextContent('Risks2');

    await user.click(within(panel).getByRole('button', { name: 'All risks' }));
    expect(location()).not.toContain('risk=');
    // The approved risk stays in the list with its status.
    expect(within(screen.getByRole('list', { name: 'Risks' })).getByRole('button', { name: /Arithmetic/ })).toHaveTextContent('Approved');
  });

  it('lists the risks of a bill whose every reminder was kept in the record', async () => {
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries, report: { ...riskReport, risks: [], record: riskReport.risks } }));
    renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });

    await risksTabWithCount(3);
    const list = await screen.findByRole('list', { name: 'Risks' });
    expect(within(list).getAllByRole('button').map((row) => row.dataset.riskId)).toEqual(riskReport.risks.map((risk) => risk.risk_id));
    expect(screen.queryByText('No risk was found in this validation.')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /kept reminder/ })).not.toBeInTheDocument();
  });

  it('decides the highlighted risk of the list with A, and opens it with Enter', async () => {
    const approved = {
      ...lineTotalIssue,
      review_status: 'confirmed_error',
      version: 2,
      reviewed_at: '2026-11-21T12:05:00Z',
      allowed_review_actions: ['pending_review', 'false_positive', 'needs_more_information'],
    };
    const api = mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [{ method: 'POST', path: '/api/v1/issues/iss_1/review', respond: { issue: approved, history: issueHistory } }],
      }),
    );
    const { user, location } = renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });

    const list = await screen.findByRole('list', { name: 'Risks' });
    const [first, second] = within(list).getAllByRole('button');
    act(() => second.focus());
    await user.keyboard('k');
    expect(first).toHaveFocus();
    await user.keyboard('a');
    await waitFor(() => expect(location()).toContain('risk=risk_total'));
    const posts = await waitFor(() => {
      const calls = api.callsTo('POST', '/api/v1/issues/iss_1/review');
      expect(calls).toHaveLength(1);
      return calls;
    });
    expect(JSON.parse(posts[0].body)).toEqual({ status: 'confirmed_error', expected_version: 1 });

    const panel = screen.getByRole('complementary', { name: 'Side panel' });
    await user.click(within(panel).getByRole('button', { name: 'All risks' }));
    const row = within(await screen.findByRole('list', { name: 'Risks' })).getAllByRole('button')[1];
    act(() => row.focus());
    await user.keyboard('{Enter}');
    await waitFor(() => expect(location()).toContain('risk=risk_price'));
  });

  it('opens a kept reminder from a link without counting it into the main list', async () => {
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries }));
    renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_note`, { activeDocumentId: 'doc_1' });

    const panel = await screen.findByRole('complementary', { name: 'Side panel' });
    expect(await within(panel).findByText(riskReport.record[0].title)).toBeInTheDocument();
    expect(within(panel).queryByText(/^Risk \d+ of \d+$/)).not.toBeInTheDocument();
  });

  it('finishes the review of a run under the Risks list once nothing is left to review', async () => {
    const ready = {
      ...runDetail,
      review_status: 'in_progress',
      issue_counts: { ...runDetail.issue_counts, by_review_status: { corrected: 1, dismissed: 1, pending_review: 0 } },
    };
    const finished = { ...ready, review_status: 'finished', review_finished_at: '2026-11-21T13:06:00Z' };
    const api = mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [
          { method: 'POST', path: '/api/v1/validation-runs/run_2/review-finish', respond: finished },
          { path: '/api/v1/validation-runs/run_2', respond: ready },
        ],
      }),
    );
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });

    const section = await screen.findByRole('region', { name: 'Review of this run' });
    await user.click(within(section).getByRole('button', { name: 'Finish review' }));
    expect(await within(section).findByText('Run review marked as finished.')).toBeInTheDocument();
    expect(api.callsTo('POST', '/api/v1/validation-runs/run_2/review-finish')).toHaveLength(1);
    expect(within(section).getByRole('button', { name: 'Reopen review' })).toBeInTheDocument();
  });

  it('approves a risk, edits its cell in the sheet, and then checks the new revision by itself', async () => {
    const approved = {
      ...lineTotalIssue,
      review_status: 'confirmed_error',
      version: 2,
      reviewed_at: '2026-11-21T12:05:00Z',
      allowed_review_actions: ['pending_review', 'false_positive', 'needs_more_information'],
    };
    const api = mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [
          { method: 'POST', path: '/api/v1/issues/iss_1/review', respond: { issue: approved, history: issueHistory } },
          { method: 'POST', path: RUNS, respond: () => jsonResponse({ ...runDetail, dataset_revision: 2 }, { status: 201 }) },
          {
            method: 'POST',
            path: '/api/v1/datasets/ds_1/corrections',
            respond: {
              dataset_id: 'ds_1',
              revision: 2,
              changed: true,
              corrections: [],
              rows: [{ ...rows[1], cells: { ...rows[1].cells, col_total: { ...rows[1].cells.col_total, raw_value: '500.00' } } }],
            },
          },
        ],
      }),
    );
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_total`, { activeDocumentId: 'doc_1' });

    const panel = await screen.findByRole('complementary', { name: 'Side panel' });
    const group = await within(panel).findByRole('group', { name: 'Review decision' });
    await screen.findByRole('rowheader', { name: '5, has open findings' });
    await user.click(within(group).getByRole('button', { name: /^Approve/ }));

    // The risk's cell opens for editing with its value selected.
    const editor = await within(screen.getByRole('grid')).findByRole('textbox', { name: /^Edit F5/ });
    expect(editor).toHaveFocus();
    await user.keyboard('500.00{Enter}');
    await waitFor(() => expect(api.callsTo('POST', '/api/v1/datasets/ds_1/corrections')).toHaveLength(1));
    expect(JSON.parse(api.callsTo('POST', '/api/v1/datasets/ds_1/corrections')[0].body)).toEqual({
      expected_revision: 1,
      corrections: [{ table_id: 'tbl_1', row_id: 'row_5', column_id: 'col_total', raw_value: '500.00' }],
    });
    // No notice that the results are out of date: the new revision is checked once edits settle.
    expect(api.callsTo('POST', RUNS)).toHaveLength(0);
    await waitFor(() => expect(api.callsTo('POST', RUNS)).toHaveLength(1), { timeout: 3000 });
    expect(screen.queryByText(/edited after this validation/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Checking…')).not.toBeInTheDocument());
  });

  it('opens the finding named in the URL in its risk, also from an old Issues link', async () => {
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries }));
    const { user, location } = renderApp(`${WORKSPACE_URL}&tab=issues&issue=iss_1`, { activeDocumentId: 'doc_1' });

    const panel = await screen.findByRole('complementary', { name: 'Side panel' });
    expect(await within(panel).findByRole('heading', { name: 'Arithmetic', level: 2 })).toBeInTheDocument();
    await user.click(within(panel).getByRole('button', { name: 'Details and evidence' }));
    expect(within(panel).getByRole('heading', { name: lineTotalIssue.title })).toBeInTheDocument();
    expect(within(panel).getByRole('group', { name: 'Review decision' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^Risks/ })).toHaveAttribute('aria-selected', 'true');
    expect(location()).toContain('issue=iss_1');
  });

  it('does not treat a run still in progress as a result', async () => {
    const running = { ...runSummaries[0], status: 'running', finished_at: null, issue_count: 0 };
    const api = mockFetch(projectWorkspaceRoutes({ runs: () => [running] }));
    renderApp(`${WORKSPACE_URL}&tab=issues`, { activeDocumentId: 'doc_1' });

    await screen.findByRole('grid', { name: 'Sheet LV' });
    await waitFor(() => expect(api.callsTo('GET', RUNS)).not.toHaveLength(0));
    expect(tabNames()).toEqual(['Properties', 'What-if', 'Quantities']);
    expect(screen.getByRole('tab', { name: 'Properties' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('rowheader', { name: /has open findings/ })).not.toBeInTheDocument();
    expect(api.callsTo('GET', ISSUES)).toHaveLength(0);
    expect(api.callsTo('GET', '/api/v1/validation-runs/run_2')).toHaveLength(0);
  });

  it('shows a reading that needs review as the reading quality in Properties, without a banner or the notes', async () => {
    const warning = {
      code: 'number_format_ambiguous',
      message: 'Ambiguous number formats.',
      table_id: 'tbl_1',
      source: null,
      count: 3,
      needs_review: true,
    };
    const detail = {
      ...documentDetail,
      dataset: { ...dataset, extraction: { ...dataset.extraction, quality: 'needs_review', warnings: [warning] } },
    };
    mockFetch(projectWorkspaceRoutes({ detail, runs: () => runSummaries }));
    const { user, location } = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });

    await risksTabWithCount(3);
    expect(screen.queryByText(/extraction warning needs review/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Show how the file was read' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Properties' }));
    expect(location()).toContain('tab=properties');
    const file = within(screen.getByRole('tabpanel')).getByRole('region', { name: 'File' });
    expect(within(file).getByText('Reading quality', { selector: 'dt' }).nextElementSibling).toHaveTextContent('Needs review');
    expect(within(screen.getByRole('tabpanel')).queryByText('Ambiguous number formats.')).not.toBeInTheDocument();
  });

  it('goes back to the files of the project through Workspace, and a file the server no longer has returns there too', async () => {
    mockFetch(
      projectWorkspaceRoutes({
        extra: [{ path: '/api/v1/documents/doc_gone', respond: errorResponse(404, 'not_found', 'Unknown document.') }],
      }),
    );
    const { user, location, unmount } = renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });

    await screen.findByRole('grid', { name: 'Sheet LV' });
    await user.click((await findProjectNav()).getByRole('link', { name: 'Workspace' }));
    expect(await screen.findByRole('heading', { level: 1, name: 'Workspace' })).toBeInTheDocument();
    expect(location()).toBe('/projects/prj_1/workspace');
    expect(screen.queryByRole('grid', { name: /^Sheet/ })).not.toBeInTheDocument();
    // The project's files to open, and the box to add more.
    const files = await screen.findByRole('region', { name: /^Files/ });
    expect(screen.getByRole('region', { name: 'Add files' })).toBeInTheDocument();
    await user.click(await within(files).findByRole('row', { name: /tender\.xlsx/ }));
    await waitFor(() => expect(location()).toBe(WORKSPACE_URL));
    expect(await screen.findByRole('grid', { name: 'Sheet LV' })).toBeInTheDocument();

    unmount();
    const missing = renderApp('/projects/prj_1/workspace?document=doc_gone');
    await waitFor(() => expect(missing.location()).toBe('/projects/prj_1/workspace'));
    expect(await screen.findByRole('region', { name: /^Files/ })).toBeInTheDocument();
  });
});
