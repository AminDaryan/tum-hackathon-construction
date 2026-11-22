import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { documentDetail, documentSummary, lineTotalIssue, outlierIssue, riskReport, runSummaries } from '../../test/fixtures.ts';
import { DEFAULT_ME, errorResponse, mockFetch as mockApi, page, type MockRoute } from '../../test/fetchMock.ts';
import { openNavigation } from '../../test/navigation.ts';
import { renderApp } from '../../test/render.tsx';
import { chooseOption, getSelect } from '../../test/select.ts';
import { workspaceRoutes } from '../../test/workspaceRoutes.ts';
import type { DocumentSummary, Project } from '../../services/apiTypes.ts';

/** The project page also lists the project's clarifications (tested in features/clarifications): none here. */
const NO_CLARIFICATIONS = { path: /^\/api\/v1\/projects\/[^/]+\/clarifications$/, respond: { items: [], total: 0, offset: 0, limit: 10 } };
const mockFetch = (routes: MockRoute[]) => mockApi([...routes, NO_CLARIFICATIONS]);

vi.mock('../../ifc-demo/ModelViewer.tsx', () => {
  function ModelViewer() {
    return <div data-testid="model-viewer" />;
  }
  return { ModelViewer };
});

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    project_id: 'prj_1',
    name: 'Riverside',
    description: 'Bridge works',
    created_at: '2026-11-21T10:00:00Z',
    status: 'in_progress',
    assignees: ['Amin'],
    decision_cutoff: null,
    files: [],
    demo_key: null,
    preparation: 'ready',
    preparation_error: null,
    validation: null,
    ...overrides,
  };
}

describe('Projects table', () => {
  it('searches and filters the projects, and clears the filters when none match', async () => {
    mockFetch([
      {
        path: '/api/v1/projects',
        respond: [
          makeProject({ project_id: 'prj_a', name: 'Riverside', description: 'Bridge works', assignees: ['Amin'] }),
          makeProject({ project_id: 'prj_b', name: 'School', description: 'Gym hall', status: 'finished', assignees: ['Larissa'] }),
          makeProject({ project_id: 'prj_c', name: 'Depot', description: '', assignees: [] }),
        ],
      },
    ]);
    const { user } = renderApp('/projects');
    const table = await screen.findByRole('grid', { name: /^Projects/ });
    await waitFor(() => expect(within(table).getAllByRole('row')).toHaveLength(4));
    // The grid is found again each time: the empty state shows another one in its place.
    const names = () => within(screen.getByRole('grid', { name: /^Projects/ })).queryAllByRole('row').slice(1).map((row) => row.textContent?.match(/^(Riverside|School|Depot)/)?.[1]);

    await user.type(screen.getByRole('searchbox', { name: 'Search projects' }), 'bridge');
    expect(names()).toEqual(['Riverside']);
    expect(screen.getByRole('heading', { name: /^All projects\s*\(1\)$/ })).toBeInTheDocument();
    await user.clear(screen.getByRole('searchbox', { name: 'Search projects' }));

    await chooseOption(user, 'Status', 'Finished');
    expect(names()).toEqual(['School']);
    await chooseOption(user, 'Assigned to', 'Amin');
    expect(screen.getByText('No projects match the search and filters')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear filters' }));
    expect(names()).toEqual(['Riverside', 'School', 'Depot']);
    expect(getSelect('Status')).toHaveTextContent('All statuses');
  });

  it('lists projects newest first with their details, and Create project opens the create page', async () => {
    mockFetch([
      { path: '/api/v1/projects/prj_old', respond: { project: makeProject({ project_id: 'prj_old', name: 'Old tender' }), documents: [], review_counts: {} } },
      ...workspaceRoutes({ runs: () => [] }),
      {
        path: '/api/v1/projects',
        respond: [
          makeProject({ project_id: 'prj_old', name: 'Old tender', created_at: '2026-11-01T10:00:00Z', status: 'finished', assignees: [] }),
          makeProject({ project_id: 'prj_new', name: 'New tender', assignees: ['Amin', 'Larissa'], files: [{ document_id: 'doc_1', role: 'bill' }] }),
        ],
      },
    ]);
    const { user, location } = renderApp('/projects');
    const table = await screen.findByRole('grid', { name: /^Projects/ });
    // The header row and the two projects.
    await waitFor(() => expect(within(table).getAllByRole('row')).toHaveLength(3));
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent(/^New tender/);
    expect(rows[1]).toHaveTextContent(/^Old tender/);
    expect(rows[0]).toHaveTextContent('Bridge works');
    expect(rows[0]).toHaveTextContent('Amin, Larissa');
    expect(rows[0]).toHaveTextContent('In progress');
    expect(rows[1]).toHaveTextContent('Finished');
    expect(within(rows[1]).getByText(/Nov 1, 2026|1 Nov 2026/)).toBeInTheDocument();

    await user.click(rows[1]);
    await waitFor(() => expect(location()).toBe('/projects/prj_old'));
    // The project's Overview, titled like its menu item; the navigation marks the project as open.
    expect(await screen.findByRole('heading', { name: 'Overview', level: 1 })).toBeInTheDocument();
    const nav = await openNavigation(user);
    expect(await nav.findByRole('link', { current: 'page' })).toHaveAccessibleName('Old tender');
  });

  it('changes the status and the assigned people in a project\'s row, without opening the project', async () => {
    let riverside = makeProject({ project_id: 'prj_a', name: 'Riverside', assignees: ['Amin'] });
    const api = mockFetch([
      { path: '/api/v1/projects', respond: () => [riverside] },
      { path: '/api/v1/collaboration/session', respond: { reviewer: null, reviewers: [{ handle: 'larissa', name: 'Larissa' }] } },
      {
        method: 'PATCH',
        path: '/api/v1/projects/prj_a',
        respond: (call) => (riverside = { ...riverside, ...JSON.parse(call.body) }),
      },
    ]);
    const { user, location } = renderApp('/projects');
    const table = await screen.findByRole('grid', { name: /^Projects/ });

    await user.click(await within(table).findByRole('button', { name: 'In progress Status of Riverside' }));
    await user.click(await screen.findByRole('option', { name: 'Finished' }));
    expect(await within(table).findByRole('button', { name: 'Finished Status of Riverside' })).toBeInTheDocument();
    expect(api.callsTo('PATCH', '/api/v1/projects/prj_a').map((call) => JSON.parse(call.body))).toEqual([{ status: 'finished' }]);

    // Ticking saves nothing until the list closes; then the people ticked are saved once.
    await user.click(within(table).getByRole('button', { name: /People assigned to Riverside/ }));
    await user.click(await screen.findByRole('option', { name: 'Larissa' }));
    expect(api.callsTo('PATCH', '/api/v1/projects/prj_a')).toHaveLength(1);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(api.callsTo('PATCH', '/api/v1/projects/prj_a')).toHaveLength(2));
    expect(JSON.parse(api.callsTo('PATCH', '/api/v1/projects/prj_a')[1].body)).toEqual({ assignees: ['Amin', 'Larissa'] });
    expect(await within(table).findByText('Amin, Larissa')).toBeInTheDocument();
    expect(location()).toBe('/projects');
  });

  it('shows a viewer the status and the assigned people without controls', async () => {
    mockFetch([
      { path: '/api/v1/me', respond: { ...DEFAULT_ME, kind: 'user', name: 'Vera', role: 'viewer', user_id: 'usr_2', permissions: ['read'] } },
      { path: '/api/v1/projects', respond: [makeProject({ project_id: 'prj_a', name: 'Riverside', assignees: ['Amin'] })] },
    ]);
    renderApp('/projects');
    const table = await screen.findByRole('grid', { name: /^Projects/ });
    expect(await within(table).findByText('Amin')).toBeInTheDocument();
    await waitFor(() => expect(within(table).queryByRole('button', { name: /Status of Riverside/ })).not.toBeInTheDocument());
    expect(within(table).queryByRole('button', { name: /People assigned to Riverside/ })).not.toBeInTheDocument();
    expect(within(table).getByText('In progress')).toBeInTheDocument();
  });

  it('puts Create project at the top right of the table', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { user, location } = renderApp('/projects');
    const section = await screen.findByRole('region', { name: /All projects/ });
    expect(await within(section).findByText('No projects yet')).toBeInTheDocument();
    await user.click(within(section).getByRole('link', { name: 'Create project' }));
    await waitFor(() => expect(location()).toBe('/projects/new'));
    expect(await screen.findByRole('heading', { name: 'Create project', level: 1 })).toBeInTheDocument();
  });
});

describe('Create project', () => {
  it('creates the project with its details and users, adds each file, and reports the files that failed', async () => {
    const project = makeProject({ assignees: ['Larissa', 'Amin'] });
    const api = mockFetch([
      {
        path: '/api/v1/collaboration/session',
        respond: { reviewer: { handle: 'larissa', name: 'Larissa' }, reviewers: [{ handle: 'larissa', name: 'Larissa' }, { handle: 'johan', name: 'Johan' }] },
      },
      { path: '/api/v1/collaboration/notifications', respond: { items: [], unread_count: 0 } },
      { method: 'POST', path: '/api/v1/projects', respond: project },
      {
        method: 'POST',
        path: '/api/v1/documents',
        respond: (call) =>
          call.body.get('file').name === 'big.x84' ? errorResponse(413, 'file_too_large', 'Upload limit exceeded.') : documentDetail,
      },
      {
        method: 'PUT',
        path: '/api/v1/projects/prj_1/documents',
        respond: () => {
          project.files = [{ document_id: 'doc_1', role: 'bill' }];
          return project;
        },
      },
      { path: '/api/v1/projects/prj_1', respond: () => ({ project, documents: [documentSummary], review_counts: {} }) },
      ...workspaceRoutes({ runs: () => [] }),
    ]);
    const { user, location } = renderApp('/projects/new');
    await user.type(await screen.findByLabelText('Name'), 'Riverside');
    await user.type(screen.getByLabelText(/Description/), 'Bridge works');

    // The reviewer signed in on this browser is assigned from the start; others are offered.
    const assigned = await screen.findByRole('list', { name: 'Assigned users' });
    expect(within(assigned).getByText('Larissa')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Assign Johan' })).toBeInTheDocument();
    const field = screen.getByRole('textbox', { name: 'Assigned users' });
    await user.type(field, 'Larissa Stoll{Enter}');
    expect(screen.getByRole('alert')).toHaveTextContent('no spaces');
    await user.clear(field);
    await user.type(field, 'Amin{Enter}');
    expect(within(assigned).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['Larissa', 'Amin']);

    fireEvent.drop(screen.getByText('Drop files here, or'), {
      dataTransfer: { files: [new File(['<GAEB/>'], 'tender.x83'), new File(['<GAEB/>'], 'big.x84'), new File(['x'], 'notes.doc')] },
    });
    expect(screen.getByRole('alert')).toHaveTextContent('legacy Word file');
    const chosen = screen.getByRole('list', { name: 'Chosen files' });
    expect(within(chosen).getAllByRole('listitem')).toHaveLength(2);

    await user.click(within(screen.getByRole('main')).getByRole('button', { name: 'Create project' }));
    await waitFor(() => expect(location()).toBe('/projects/prj_1'));
    expect(JSON.parse(api.callsTo('POST', '/api/v1/projects')[0].body)).toEqual({
      name: 'Riverside',
      description: 'Bridge works',
      assignees: ['Larissa', 'Amin'],
    });
    expect(api.callsTo('POST', '/api/v1/documents')).toHaveLength(2);
    expect(api.callsTo('POST', '/api/v1/documents')[0].body.get('profile_id')).toBe('boq');
    expect(api.callsTo('PUT', '/api/v1/projects/prj_1/documents')).toHaveLength(1);
    expect(await screen.findByText('1 file could not be added')).toBeInTheDocument();
    expect(screen.getByText('big.x84: Upload limit exceeded.')).toBeInTheDocument();
  });

  it('edits the details of a project', async () => {
    const project = makeProject();
    const api = mockFetch([
      { path: '/api/v1/projects/prj_1', respond: () => ({ project, documents: [], review_counts: {} }) },
      {
        method: 'PATCH',
        path: '/api/v1/projects/prj_1',
        respond: (call) => {
          Object.assign(project, JSON.parse(call.body));
          return project;
        },
      },
    ]);
    const { user, location } = renderApp('/projects/prj_1');
    await user.click(await screen.findByRole('link', { name: 'Edit' }));
    const name = await screen.findByLabelText('Name');
    expect(name).toHaveValue('Riverside');
    await user.click(screen.getByRole('button', { name: 'Remove Amin' }));
    await user.clear(name);
    await user.type(name, 'Riverside bridge');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(location()).toBe('/projects/prj_1'));
    expect(JSON.parse(api.callsTo('PATCH', '/api/v1/projects/prj_1')[0].body)).toEqual({
      name: 'Riverside bridge',
      description: 'Bridge works',
      assignees: [],
    });
    expect(await screen.findByRole('heading', { name: 'Overview', level: 1 })).toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  });
});

describe('Project page', () => {
  const validated = () =>
    makeProject({
      files: [
        { document_id: 'doc_1', role: 'bill' },
        { document_id: 'doc_2', role: 'reference' },
      ],
      validation: {
        status: 'completed',
        started_at: '2026-11-21T10:00:00Z',
        finished_at: '2026-11-21T10:01:00Z',
        runs: { doc_1: 'run_2' },
        skipped: { doc_2: 'Reference: compared, not validated as a bill' },
        comparisons: [],
        error: null,
      },
    });
  const reference = { ...documentSummary, document_id: 'doc_2', original_filename: 'prices.csv', dataset_id: 'ds_2', last_run: null, uploaded_at: '2026-11-16T08:00:00Z' };

  it('gives the overview of the whole project: its status and actions, figures over all its bills, its risks, the follow-ups and the files', async () => {
    const project = validated();
    project.files.push({ document_id: 'doc_3', role: 'bill' });
    project.validation!.runs.doc_3 = 'run_3';
    const second = { ...documentSummary, document_id: 'doc_3', original_filename: 'lot2.x83', dataset_id: 'ds_3', uploaded_at: '2026-11-18T08:00:00Z' };
    // A drawing the server put among the supporting documents: listed as one, without bill errors.
    project.files.push({ document_id: 'doc_4', role: 'bill' });
    const drawing = {
      ...documentSummary,
      document_id: 'doc_4',
      original_filename: 'drawing.pdf',
      format: 'pdf' as const,
      processing_status: 'failed' as const,
      failure_reason: 'No bill of quantities table found',
      dataset_id: null,
      last_run: null,
      uploaded_at: '2026-11-19T08:00:00Z',
    };
    const api = mockFetch([
      {
        path: '/api/v1/projects/prj_1',
        respond: {
          project,
          documents: [reference, documentSummary, second, drawing],
          groups: { doc_1: 'bill', doc_2: 'bill', doc_3: 'bill', doc_4: 'support' },
          review_counts: {
            doc_1: { findings: 4, to_review: 2, high_priority: 1, by_severity: { high: 1, medium: 3 } },
            doc_3: { findings: 6, to_review: 3, high_priority: 0, by_severity: { low: 6 } },
          },
        },
      },
      { path: '/api/v1/projects/prj_1/top-issues', respond: { items: [lineTotalIssue, outlierIssue], total: 2 } },
      { path: '/api/v1/projects', respond: [project] },
      ...workspaceRoutes({ runs: () => runSummaries, issues: [lineTotalIssue, outlierIssue] }),
    ]);
    const { user, location } = renderApp('/projects/prj_1');

    // No tabs: the overview carries Edit and the project's status at its top right, and no Risk report.
    expect(await screen.findByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    const overview = screen.getByRole('region', { name: 'Project overview' });
    expect(within(overview).getByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/projects/prj_1/edit');
    // The status shows once the project has loaded.
    expect(await waitFor(() => getSelect('Status', overview))).toHaveTextContent('In progress');
    expect(within(overview).queryByRole('link', { name: 'Risk report' })).not.toBeInTheDocument();
    expect(within(overview).queryByRole('button', { name: 'Mark as finished' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Next best action' })).not.toBeInTheDocument();

    // Figures over both bills: 2 bills, 10 findings, 5 to review.
    const figures = within(overview).getAllByRole('definition').slice(0, 3);
    expect(figures.map((item) => item.textContent)).toEqual(['2', '10', '5']);
    // The findings by priority, highest first.
    const risks = within(overview).getByRole('region', { name: 'Risks' });
    expect(within(risks).getAllByRole('term').map((item) => item.textContent)).toEqual(['Critical', 'High', 'Medium', 'Low', 'Info']);
    expect(within(risks).getAllByRole('definition').map((item) => item.textContent)).toEqual(['0', '1', '3', '6', '0']);

    // Under them the project's risks, in the server's order (the most severe first), a page of them.
    const list = await within(overview).findByRole('grid', { name: /^Risks/ });
    const riskRows = (await within(list).findAllByRole('row')).slice(1);
    expect(riskRows).toHaveLength(2);
    expect(riskRows[0]).toHaveTextContent('HighLine total does not equal quantity × unit pricetender.xlsx20.00 EUR');
    expect(riskRows[1]).not.toHaveTextContent('EUR');
    expect(riskRows[1]).not.toHaveTextContent('—');
    expect(within(overview).getByRole('navigation', { name: 'risks pages' })).toHaveTextContent('1–2 of 2 risks');
    const asked = api.callsTo('GET', '/api/v1/projects/prj_1/top-issues')[0].query;
    expect([asked.get('limit'), asked.get('offset')]).toEqual(['5', '0']);

    // Every file of the project in one table, the newest upload first.
    const filesBox = screen.getByRole('region', { name: /^Files/ });
    const files = screen.getByRole('grid', { name: /^Files/ });
    const rows = within(files).getAllByRole('row').slice(1);
    expect(rows.map((row) => within(row).getByRole('rowheader').textContent)).toEqual(['drawing.pdf', 'lot2.x83', 'tender.xlsx', 'prices.csv']);
    expect(rows[2]).toHaveTextContent('2, 1 high');
    expect(files).not.toHaveTextContent('Validating…');
    // The drawing as a supporting document, without bill errors.
    expect(rows[0]).toHaveTextContent('Supporting document');
    expect(rows[0]).not.toHaveTextContent('No bill of quantities table found');
    expect(rows[0]).not.toHaveTextContent('Needs attention');
    expect(rows[3]).toHaveTextContent('Compared');
    expect(rows[3]).toHaveTextContent('Reference');
    expect(rows[3]).not.toHaveTextContent('Needs attention');
    expect(screen.queryByRole('region', { name: /^Supporting documents/ })).not.toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'files pages' })).toHaveTextContent('1–4 of 4 files');
    expect(filesBox).toHaveAccessibleName(/^Files ?\(4\)$/);
    expect(filesBox).toContainElement(screen.getByRole('button', { name: 'Validate project' }));
    await chooseOption(user, 'State', 'High-priority findings', filesBox);
    expect(within(screen.getByRole('grid', { name: /^Files/ })).getAllByRole('row')).toHaveLength(2);
    expect(filesBox).toHaveAccessibleName(/^Files ?\(1\)$/);
    expect(screen.getByRole('region', { name: 'Add files' })).toBeInTheDocument();
    // The differences between files are no longer shown; the follow-ups are, empty here.
    expect(screen.queryByRole('region', { name: /Differences between files/ })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: /^Follow-ups/ })).toHaveTextContent('No clarifications yet');

    // A risk opens in the Workspace at that finding.
    await user.click(within(riskRows[0]).getByText('Line total does not equal quantity × unit price'));
    await waitFor(() => expect(location()).toBe('/projects/prj_1/workspace?document=doc_1&run=run_2&issue=iss_1&tab=risks'));

    // The project's name before the file's leads back to the project's Overview.
    await user.click(await within(screen.getByRole('banner', { name: 'Top bar' })).findByRole('link', { name: 'Riverside' }));
    await waitFor(() => expect(location()).toBe('/projects/prj_1'));
    // The clarifications are on Follow-ups, not on the Overview.
    expect(await screen.findByRole('region', { name: 'Project overview' })).toBeInTheDocument();
    expect(getSelect('State', screen.getByRole('region', { name: /^Files/ }))).toHaveTextContent('High-priority findings');
    expect(screen.queryByRole('region', { name: 'Clarifications' })).not.toBeInTheDocument();
  });

  it('shows the size of a discrepancy and a comparison with reference prices as a comparison, never as a loss', async () => {
    const stated = (amount: string, kind: 'discrepancy' | 'reference_deviation') => ({
      ...lineTotalIssue.estimated_financial_impact!,
      amount,
      kind,
    });
    // The backend may send fewer decimals ("-2400.0"): money always shows cents.
    const discrepancy = { ...lineTotalIssue, estimated_financial_impact: stated('-2400.0', 'discrepancy') };
    const comparison = { ...lineTotalIssue, issue_id: 'iss_3', estimated_financial_impact: stated('-228600.00', 'reference_deviation') };
    mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project: validated(), documents: [documentSummary, reference], review_counts: {} } },
      { path: '/api/v1/projects/prj_1/top-issues', respond: { items: [discrepancy, comparison], total: 2 } },
      ...workspaceRoutes({ runs: () => runSummaries }),
    ]);
    renderApp('/projects/prj_1');
    const list = await within(await screen.findByRole('region', { name: 'Project overview' })).findByRole('grid', { name: /^Risks/ });
    const riskRows = (await within(list).findAllByRole('row')).slice(1);
    expect(riskRows[0]).toHaveTextContent(/tender\.xlsx2,400\.00 EUR$/);
    expect(riskRows[1]).toHaveTextContent(/tender\.xlsxComparison: 228,600\.00 EUR$/);
  });

  it('reads the project again on the Overview and the files to choose from, after decisions made in the Workspace', async () => {
    let toReview = 2;
    mockFetch([
      {
        path: '/api/v1/projects/prj_1',
        respond: () => ({
          project: validated(),
          documents: [documentSummary, reference],
          review_counts: { doc_1: { findings: 4, to_review: toReview, high_priority: toReview, by_severity: { high: 4 } } },
        }),
      },
      { path: '/api/v1/projects/prj_1/top-issues', respond: { items: [], total: 0 } },
      { path: '/api/v1/projects', respond: [validated()] },
      ...workspaceRoutes({ runs: () => runSummaries, issues: [lineTotalIssue, outlierIssue] }),
    ]);
    const { user } = renderApp('/projects/prj_1/workspace?document=doc_1');
    // A decision in the open file leaves one finding to review.
    await screen.findByRole('heading', { level: 1, name: 'tender.xlsx' });
    toReview = 1;
    await user.click(within(screen.getByRole('navigation', { name: 'Project' })).getByRole('link', { name: 'Workspace' }));
    const files = await screen.findByRole('grid', { name: /^Files/ });
    await waitFor(() => expect(within(files).getAllByRole('row')[1]).toHaveTextContent('1, 1 high'));

    toReview = 0;
    await user.click(within(screen.getByRole('navigation', { name: 'Project' })).getByRole('link', { name: 'Overview' }));
    const overview = await screen.findByRole('region', { name: 'Project overview' });
    await waitFor(() => expect(within(overview).getAllByRole('definition')[2]).toHaveTextContent('0'));
  });

  it('says a project without a validation result is not validated yet, rather than showing zero findings', async () => {
    const project = makeProject({ files: [{ document_id: 'doc_1', role: 'bill' }] });
    mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project, documents: [{ ...documentSummary, last_run: null }], review_counts: {} } },
      ...workspaceRoutes({ runs: () => [] }),
    ]);
    renderApp('/projects/prj_1');
    const overview = await screen.findByRole('region', { name: 'Project overview' });
    // The overview is laid out while the project loads; its figures follow.
    await waitFor(() =>
      expect(within(overview).getAllByRole('definition').slice(0, 3).map((item) => item.textContent)).toEqual(['1', 'Not validated', 'Not validated']),
    );
    const risks = within(overview).getByRole('region', { name: 'Risks' });
    expect(within(risks).getAllByRole('definition').map((item) => item.textContent)).toEqual(['—', '—', '—', '—', '—']);
    expect(overview).toHaveTextContent('Not validated yet');
    expect(within(screen.getByRole('grid', { name: /^Files/ })).getAllByRole('row')[1]).toHaveTextContent('Not validated');
  });

  it('keeps the risks page when returning from a finding', async () => {
    const project = validated();
    const api = mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project, documents: [documentSummary, reference], review_counts: {} } },
      { path: '/api/v1/projects/prj_1/top-issues', respond: { items: [lineTotalIssue, outlierIssue], total: 12 } },
      ...workspaceRoutes({ runs: () => runSummaries }),
    ]);
    const { user } = renderApp('/projects/prj_1');
    const overview = await screen.findByRole('region', { name: 'Project overview' });
    const pages = await within(overview).findByRole('navigation', { name: 'risks pages' });
    expect(pages).toHaveTextContent('1–5 of 12 risks');
    await user.click(within(pages).getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(api.callsTo('GET', '/api/v1/projects/prj_1/top-issues')).toHaveLength(2));
    const asked = api.callsTo('GET', '/api/v1/projects/prj_1/top-issues')[1].query;
    expect([asked.get('limit'), asked.get('offset')]).toEqual(['5', '5']);
    expect(await within(overview).findByRole('navigation', { name: 'risks pages' })).toHaveTextContent('6–10 of 12 risks');
    await user.click(within(overview).getByText(lineTotalIssue.title));
    await user.click(await within(screen.getByRole('banner', { name: 'Top bar' })).findByRole('link', { name: 'Riverside' }));
    expect(await screen.findByRole('navigation', { name: 'risks pages' })).toHaveTextContent('6–10 of 12 risks');
  });

  it('keeps the follow-ups page when returning from a bidder question', async () => {
    const project = validated();
    const clarification = {
      clarification_id: 'clr_1',
      project_id: 'prj_1',
      document_id: 'doc_1',
      risk_id: 'risk_soil',
      tier: 'high',
      kind: 'bidder_question',
      title: 'Rock layer in anchor zone: drilling method?',
      status: 'sent',
      due: null,
      phase: 'bid',
      answer: '',
      created_at: '2026-11-21T10:00:00Z',
      updated_at: '2026-11-21T10:00:00Z',
    };
    const api = mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project, documents: [documentSummary, reference], review_counts: {} } },
      { path: '/api/v1/projects/prj_1/top-issues', respond: { items: [] } },
      { path: '/api/v1/projects/prj_1/clarifications', respond: { items: [clarification], total: 12, offset: 0, limit: 6 } },
      ...workspaceRoutes({ runs: () => runSummaries }),
    ]);
    const { user, location } = renderApp('/projects/prj_1');

    const followUps = await screen.findByRole('grid', { name: /^Follow-ups/ });
    const row = (await within(followUps).findAllByRole('row'))[1];
    expect(row).toHaveTextContent('Bidder question');
    expect(row).toHaveTextContent('Rock layer in anchor zone: drilling method?');
    expect(row).toHaveTextContent('tender.xlsx');
    expect(row).toHaveTextContent('Sent');
    expect(screen.getByRole('region', { name: /^Follow-ups/ })).toHaveTextContent('(12)');
    // One page from the server, of the rows the card has room for, not the whole list.
    expect(api.callsTo('GET', '/api/v1/projects/prj_1/clarifications').map((call) => call.query.toString())).toEqual(['offset=0&limit=6']);

    await user.click(within(screen.getByRole('navigation', { name: 'clarifications pages' })).getByRole('button', { name: 'Next' }));
    await screen.findByText('7–12 of 12 clarifications');
    await user.click(await screen.findByText('Rock layer in anchor zone: drilling method?'));
    await waitFor(() => expect(location()).toBe('/projects/prj_1/workspace?document=doc_1&risk=risk_soil&tab=risks'));
    await user.click(await within(screen.getByRole('banner', { name: 'Top bar' })).findByRole('link', { name: 'Riverside' }));
    expect(await screen.findByRole('navigation', { name: 'clarifications pages' })).toHaveTextContent('7–12 of 12 clarifications');
    expect(api.callsTo('GET', '/api/v1/projects/prj_1/clarifications').at(-1)?.query.get('offset')).toBe('6');
  });

  it('searches the files by name, filters them by type, and clears the filters when none match', async () => {
    const docs = [
      { ...documentSummary, document_id: 'doc_1', original_filename: 'Abgabe LV.pdf', last_run: null, uploaded_at: '2026-11-22T09:50:00Z' },
      { ...documentSummary, document_id: 'doc_2', original_filename: 'Rohbau Los 1.x83', last_run: null, uploaded_at: '2026-11-21T09:00:00Z' },
      { ...documentSummary, document_id: 'doc_3', original_filename: 'Bodengutachten.pdf', format: 'pdf' as const, dataset_id: null, last_run: null, uploaded_at: '2026-11-20T09:00:00Z' },
    ];
    const project = makeProject({ files: docs.map((doc) => ({ document_id: doc.document_id, role: 'bill' })) });
    mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project, documents: docs, groups: { doc_1: 'bill', doc_2: 'bill', doc_3: 'support' }, review_counts: {} } },
      ...workspaceRoutes({ runs: () => [] }),
    ]);
    const { user } = renderApp('/projects/prj_1');
    const box = await screen.findByRole('region', { name: /^Files/ });
    const names = () => within(within(box).getByRole('grid', { name: /^Files/ })).queryAllByRole('row').slice(1).map((row) => within(row).getByRole('rowheader').textContent);
    // The newest upload first.
    await waitFor(() => expect(names()).toEqual(['Abgabe LV.pdf', 'Rohbau Los 1.x83', 'Bodengutachten.pdf']));

    // The search reads the name, in any case and without accents.
    await user.type(within(box).getByRole('searchbox', { name: 'Search files' }), 'abgabe');
    expect(names()).toEqual(['Abgabe LV.pdf']);
    expect(box).toHaveAccessibleName(/^Files ?\(1\)$/);
    await user.clear(within(box).getByRole('searchbox', { name: 'Search files' }));

    await chooseOption(user, 'Type', 'Bills', box);
    expect(names()).toEqual(['Abgabe LV.pdf', 'Rohbau Los 1.x83']);
    await chooseOption(user, 'Type', 'Supporting documents', box);
    expect(names()).toEqual(['Bodengutachten.pdf']);
    await chooseOption(user, 'State', 'Needing attention', box);
    expect(within(box).getByText('No files match the search and filters')).toBeInTheDocument();
    await user.click(within(box).getByRole('button', { name: 'Clear filters' }));
    expect(names()).toEqual(['Abgabe LV.pdf', 'Rohbau Los 1.x83', 'Bodengutachten.pdf']);
    expect(getSelect('Type', box)).toHaveTextContent('All types');
  });

  it('pages through the files, six a page', async () => {
    const docs = Array.from({ length: 8 }, (_, index) => ({
      ...documentSummary,
      document_id: `doc_${index + 1}`,
      original_filename: `bill-${index + 1}.x83`,
      last_run: null,
    }));
    const project = makeProject({ files: docs.map((doc) => ({ document_id: doc.document_id, role: 'bill' })) });
    mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project, documents: docs, review_counts: {} } },
      ...workspaceRoutes({ runs: () => [] }),
    ]);
    const { user } = renderApp('/projects/prj_1');
    const files = await screen.findByRole('grid', { name: /^Files/ });
    expect(within(files).getAllByRole('row')).toHaveLength(7);
    const pages = screen.getByRole('navigation', { name: 'files pages' });
    expect(pages).toHaveTextContent('1–6 of 8 files');
    await user.click(within(pages).getByRole('button', { name: 'Next' }));
    expect(pages).toHaveTextContent('7–8 of 8 files');
    expect(within(files).getAllByRole('row').slice(1).map((row) => within(row).getByRole('rowheader').textContent)).toEqual([
      'bill-7.x83',
      'bill-8.x83',
    ]);
  });

  it('leads with Validate project before the bills are validated, and marks the project finished', async () => {
    const project = makeProject({ files: [{ document_id: 'doc_1', role: 'bill' }] });
    const api = mockFetch([
      { path: '/api/v1/projects/prj_1', respond: () => ({ project, documents: [{ ...documentSummary, last_run: null }], review_counts: {} }) },
      {
        method: 'POST',
        path: '/api/v1/projects/prj_1/validation',
        respond: () => {
          project.validation = {
            status: 'running',
            started_at: '2026-11-21T10:00:00Z',
            finished_at: null,
            runs: {},
            skipped: {},
            comparisons: [],
            error: null,
          };
          return project;
        },
      },
      {
        method: 'PATCH',
        path: '/api/v1/projects/prj_1',
        respond: (call) => {
          Object.assign(project, JSON.parse(call.body));
          return project;
        },
      },
      ...workspaceRoutes({ runs: () => [] }),
    ]);
    const { user } = renderApp('/projects/prj_1');
    const overview = await screen.findByRole('region', { name: 'Project overview' });
    // The Risks chart is there before a validation too, without counts, and the list of risks
    // says it is not validated yet, with no pages.
    const risks = within(overview).getByRole('region', { name: 'Risks' });
    await waitFor(() => expect(within(risks).getAllByRole('definition')[0]).toHaveTextContent('—'));
    expect(within(risks).getAllByRole('definition').map((item) => item.textContent)).toEqual(['—', '—', '—', '—', '—']);
    expect(overview).toHaveTextContent('Not validated yet');
    expect(within(overview).queryByRole('navigation', { name: 'risks pages' })).not.toBeInTheDocument();
    expect(overview).not.toHaveTextContent('Validate the project');
    expect(api.callsTo('GET', '/api/v1/projects/prj_1/top-issues')).toHaveLength(0);
    const files = screen.getByRole('region', { name: /^Files/ });
    expect(screen.getAllByRole('button', { name: 'Validate project' })).toHaveLength(1);

    await user.click(within(files).getByRole('button', { name: 'Validate project' }));
    expect(api.callsTo('POST', '/api/v1/projects/prj_1/validation')).toHaveLength(1);
    expect(await within(files).findByRole('button', { name: 'Validating…' })).toBeInTheDocument();
    // The file being validated shows a spinner, named for screen readers, and no "Not validated".
    const row = within(files).getByRole('row', { name: /tender\.xlsx/ });
    await waitFor(() => expect(row).toHaveTextContent('Validating…'));
    expect(row).not.toHaveTextContent('Not validated');
    expect(screen.getByLabelText('Choose files to upload')).toBeDisabled();

    // The status is a dropdown: choosing Finished saves it, and In progress reopens the project.
    await chooseOption(user, 'Status', 'Finished');
    expect(JSON.parse(api.callsTo('PATCH', '/api/v1/projects/prj_1')[0].body)).toEqual({ status: 'finished' });
    await waitFor(() => expect(getSelect('Status')).toHaveTextContent('Finished'));
    await chooseOption(user, 'Status', 'In progress');
    expect(JSON.parse(api.callsTo('PATCH', '/api/v1/projects/prj_1')[1].body)).toEqual({ status: 'in_progress' });
  });

  it('adds several dropped files as bills, keeping the successes and naming each failure', async () => {
    const project = makeProject();
    const docs: DocumentSummary[] = [];
    const api = mockFetch([
      { path: '/api/v1/projects/prj_1', respond: () => ({ project, documents: docs, review_counts: {} }) },
      {
        method: 'POST',
        path: '/api/v1/documents',
        respond: (call) =>
          call.body.get('file').name === 'bad.d86' ? errorResponse(413, 'file_too_large', 'Upload limit exceeded.') : documentDetail,
      },
      {
        method: 'PUT',
        path: '/api/v1/projects/prj_1/documents',
        respond: () => {
          project.files = [{ document_id: 'doc_1', role: 'bill' }];
          docs.splice(0, docs.length, { ...documentSummary, last_run: null });
          return project;
        },
      },
      ...workspaceRoutes({ runs: () => [] }),
    ]);
    renderApp('/projects/prj_1');
    expect(await screen.findByText('No files yet. Add the bills of this project.')).toBeInTheDocument();
    const box = within(screen.getByRole('region', { name: 'Add files' })).getByText('Drop files here, or');
    fireEvent.dragEnter(box, { dataTransfer: { types: ['Files'] } });
    expect(screen.getByText('Drop the files to add them')).toBeInTheDocument();
    fireEvent.drop(box, { dataTransfer: { files: [new File(['<GAEB/>'], 'good.x83'), new File(['<GAEB/>'], 'bad.d86')] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('bad.d86: Upload limit exceeded.');
    expect(await screen.findByRole('row', { name: /tender\.xlsx/ })).toBeInTheDocument();
    expect(screen.getByText('Added: 1 file. Could not be added: 1 file.')).toBeInTheDocument();
    expect(api.callsTo('POST', '/api/v1/documents')).toHaveLength(2);
    expect(JSON.parse(api.callsTo('PUT', '/api/v1/projects/prj_1/documents')[0].body)).toEqual({ document_id: 'doc_1', role: 'bill' });
    expect(await screen.findByRole('button', { name: 'Validate project' })).toBeInTheDocument();
  });

  it('removes a file from the project only after asking, and says what removing does', async () => {
    const project = makeProject({ files: [{ document_id: 'doc_1', role: 'bill' }] });
    const docs: DocumentSummary[] = [{ ...documentSummary, last_run: null }];
    const api = mockFetch([
      { path: '/api/v1/projects/prj_1', respond: () => ({ project, documents: docs, review_counts: {} }) },
      {
        method: 'DELETE',
        path: '/api/v1/projects/prj_1/documents/doc_1',
        respond: () => {
          project.files = [];
          docs.splice(0);
          return project;
        },
      },
      ...workspaceRoutes({ runs: () => [] }),
    ]);
    const { user } = renderApp('/projects/prj_1');
    const remove = async () => {
      await user.click(await screen.findByRole('button', { name: 'Actions for tender.xlsx' }));
      await user.click(await screen.findByRole('menuitem', { name: 'Remove from project' }));
      return screen.findByRole('alertdialog', { name: 'Remove tender.xlsx from this project?' });
    };

    const dialog = await remove();
    expect(dialog).toHaveTextContent('The uploaded file is kept, and stays in any other project that uses it.');
    expect(dialog).toHaveTextContent('Validate the project again afterwards; the decisions made so far are kept.');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(api.callsTo('DELETE', '/api/v1/projects/prj_1/documents/doc_1')).toHaveLength(0);

    await user.click(within(await remove()).getByRole('button', { name: 'Remove from project' }));
    await waitFor(() => expect(api.callsTo('DELETE', '/api/v1/projects/prj_1/documents/doc_1')).toHaveLength(1));
    expect(await screen.findByText('No files yet. Add the bills of this project.')).toBeInTheDocument();
  });

  it('adds every file as a bill, with no choice of role or other options', async () => {
    const project = makeProject();
    mockFetch([{ path: '/api/v1/projects/prj_1', respond: { project, documents: [], review_counts: {} } }, ...workspaceRoutes({ runs: () => [] })]);
    renderApp('/projects/prj_1');
    const card = await screen.findByRole('region', { name: 'Add files' });
    expect(within(card).queryByRole('button', { name: 'More options' })).not.toBeInTheDocument();
    expect(within(card).queryByText('Add the files as')).not.toBeInTheDocument();
  });

  it('lays the page out while the project loads: its boxes, with grey figures and rows', async () => {
    let answer: (body: unknown) => void = () => {};
    const project = makeProject();
    mockFetch([
      { path: '/api/v1/projects/prj_1', respond: () => new Promise((resolve) => (answer = resolve)) },
      ...workspaceRoutes({ runs: () => [] }),
    ]);
    renderApp('/projects/prj_1');

    expect(await screen.findByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument();
    const overview = screen.getByRole('region', { name: 'Project overview' });
    // The figures and the counts by priority are not known yet: grey, not zero.
    expect(within(overview).getAllByRole('definition').map((item) => item.textContent)).toEqual(['', '', '', '', '', '', '', '']);
    expect(within(overview).getByRole('status')).toHaveTextContent('Loading the risks…');
    expect(screen.getByRole('region', { name: /^Files/ })).toHaveTextContent('Loading the files…');
    expect(screen.getByRole('region', { name: /^Follow-ups/ })).toHaveTextContent('Loading the clarifications…');
    // Adding files waits until it is known whether a validation runs, without saying so.
    const addFiles = screen.getByRole('region', { name: 'Add files' });
    expect(addFiles).toHaveTextContent('Drop files here, or');
    expect(within(addFiles).getByRole('button', { name: 'Add files…' })).toBeDisabled();

    answer({ project, documents: [], review_counts: {} });
    expect(await waitFor(() => getSelect('Status', overview))).toHaveTextContent('In progress');
    expect(within(overview).getAllByRole('definition')[0]).toHaveTextContent('0');
    expect(within(addFiles).getByRole('button', { name: 'Add files…' })).toBeEnabled();
  });

  it('opens the file chooser on a click anywhere in the upload box, once', async () => {
    const project = makeProject();
    mockFetch([{ path: '/api/v1/projects/prj_1', respond: { project, documents: [], review_counts: {} } }, ...workspaceRoutes({ runs: () => [] })]);
    const { user } = renderApp('/projects/prj_1');
    const card = await screen.findByRole('region', { name: 'Add files' });
    await waitFor(() => expect(within(card).getByRole('button', { name: 'Add files…' })).toBeEnabled());
    const click = vi.spyOn(within(card).getByLabelText('Choose files to upload'), 'click');

    await user.click(within(card).getByText('Drop files here, or'));
    expect(click).toHaveBeenCalledTimes(1);
    await user.click(within(card).getByRole('button', { name: 'Add files…' }));
    expect(click).toHaveBeenCalledTimes(2);
  });
});
