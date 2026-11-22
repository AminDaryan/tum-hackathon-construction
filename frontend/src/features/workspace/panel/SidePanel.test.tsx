import { screen, waitFor, within } from '@testing-library/react';
import { chooseOption } from '../../../test/select.ts';
import { describe, expect, it, vi } from 'vitest';
import { DEFAULT_HEALTH, mockFetch } from '../../../test/fetchMock.ts';
import {
  issueHistory,
  lineTotalIssue,
  riskReport,
  rows,
  runSummaries,
} from '../../../test/fixtures.ts';
import { renderApp } from '../../../test/render.tsx';
import { translator } from '../../../i18n/messages.ts';
import { LANGUAGE_STORAGE_KEY } from '../../../i18n/I18nProvider.tsx';
import { projectWorkspaceRoutes, RISK_REVIEWS, RISKS, WORKSPACE_URL } from '../../../test/workspaceRoutes.ts';

vi.mock('../../../ifc-demo/ModelViewer.tsx', () => {
  function ModelViewer() {
    return <div data-testid="model-viewer" />;
  }
  return { ModelViewer };
});

/** Row 5 with a unit price that is a number (the shared fixture's is ambiguous). */
const pricedRows = {
  items: [
    rows[0],
    {
      ...rows[1],
      cells: {
        ...rows[1].cells,
        col_qty: { ...rows[1].cells.col_qty, normalized_value: { kind: 'number', value: '12.5' } },
        col_price: { ...rows[1].cells.col_price, raw_value: '40.00', parse_status: 'exact', parse_note: null, normalized_value: { kind: 'number', value: '40.00' } },
        col_total: { ...rows[1].cells.col_total, normalized_value: { kind: 'number', value: '520.00' } },
      },
    },
    rows[2],
  ],
  total: 3,
  offset: 0,
  limit: 100,
};

function panel() {
  return screen.getByRole('complementary', { name: 'Side panel' });
}

/** Waits until the workspace shows the side panel. */
function findPanel() {
  return screen.findByRole('complementary', { name: 'Side panel' });
}

describe('Side panel', () => {
  it.each(['en', 'de'] as const)('cancels only the unsaved note draft (%s)', async (language) => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    const t = translator(language);
    const api = mockFetch(projectWorkspaceRoutes({
      runs: () => runSummaries,
      extra: [{ path: RISK_REVIEWS, respond: { run_id: 'run_2', items: [{
        risk_id: 'risk_soil', status: 'in_review', comment: 'Existing saved note', reviewed_at: '2026-11-21T12:05:00Z',
      }] } }],
    }));
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_soil`, { activeDocumentId: 'doc_1' });
    const decision = await screen.findByRole('group', { name: t('Review decision') });
    const add = () => within(decision).getByRole('button', { name: t('Add a note') });
    const editor = () => within(decision).getByRole('textbox', { name: t('Note (optional)') });
    const cancel = () => within(decision).getByRole('button', { name: t('Cancel') });
    const before = decision.textContent;

    for (const draft of ['', '   ', 'cleared']) {
      await user.click(add());
      if (draft) await user.type(editor(), draft);
      if (draft === 'cleared') await user.clear(editor());
      await user.click(cancel());
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(within(decision).queryByRole('textbox')).not.toBeInTheDocument();
      expect(add()).toHaveFocus();
    }

    await user.click(add());
    await user.type(editor(), 'Unsaved draft');
    await user.click(cancel());
    let dialog = screen.getByRole('alertdialog', { name: t('Discard unsaved note?') });
    await user.click(within(dialog).getByRole('button', { name: t('Continue editing') }));
    expect(editor()).toHaveValue('Unsaved draft');
    await user.click(cancel());
    await user.keyboard('{Escape}');
    expect(editor()).toHaveValue('Unsaved draft');
    await user.click(cancel());
    dialog = screen.getByRole('alertdialog', { name: t('Discard unsaved note?') });
    await user.click(within(dialog).getByRole('button', { name: t('Discard changes') }));
    expect(within(decision).queryByRole('textbox')).not.toBeInTheDocument();
    expect(decision.textContent).toBe(before);
    await user.click(add());
    expect(editor()).toHaveValue('');
    expect(within(decision).getByText('Existing saved note')).toBeInTheDocument();
    expect(api.calls.filter((call) => call.method !== 'GET')).toEqual([]);
  });

  it('Risks list: priority badge, short title, status and classification', async () => {
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries }));
    renderApp(WORKSPACE_URL, { activeDocumentId: 'doc_1' });

    // With a run the Risks tab opens by itself, right after Properties.
    const list = await screen.findByRole('list', { name: 'Risks' });
    const tabs = within(panel()).getAllByRole('tab').map((tab) => tab.textContent);
    expect(tabs[0]).toBe('Properties');
    expect(tabs[1]).toMatch(/^Risks/);
    expect(tabs.slice(2)).toEqual(['What-if', 'Quantities']);
    // tender.xlsx has no linked 3D model, so the panel has no tab for one.
    expect(tabs).toHaveLength(4);
    expect(screen.getByRole('tab', { name: /^Risks/ })).toHaveAttribute('aria-selected', 'true');
    const [total, price, soil] = within(list).getAllByRole('button');
    expect(total).toHaveTextContent('Priority High');
    expect(total).toHaveTextContent('Arithmetic');
    expect(total).toHaveTextContent('Open');
    expect(total).toHaveTextContent('Error');
    expect(price).toHaveTextContent('Comparison: 300.00 EUR');
    expect(soil).toHaveTextContent('Ambiguity');
    // No confidence percentage anywhere in the list.
    expect(list.textContent).not.toMatch(/\d\s?%/);
    expect(within(panel()).queryByText(/AI Risk Insights/)).not.toBeInTheDocument();
  });

  it('Risk detail: what is wrong, what to do, and the details behind a disclosure', async () => {
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries }));
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_total`, { activeDocumentId: 'doc_1' });

    const heading = await within(await findPanel()).findByRole('heading', { name: 'Arithmetic', level: 2 });
    expect(heading).toBeInTheDocument();
    expect(within(panel()).getByRole('heading', { name: "What's wrong" })).toBeInTheDocument();
    expect(within(panel()).getByText('Line total of 01.001 does not add up')).toBeInTheDocument();
    expect(within(panel()).getByRole('heading', { name: 'What to do' })).toBeInTheDocument();
    expect(within(panel()).queryByText(/Found by \d+ rules/)).not.toBeInTheDocument();

    await user.click(within(panel()).getByRole('button', { name: 'Details and evidence' }));
    expect(within(panel()).getAllByText('Money at stake')[0].nextElementSibling).toHaveTextContent('20.00 EUR');
    expect(within(panel()).getByText('Evidence certainty').nextElementSibling).toHaveTextContent('Confirmed');
    expect(within(panel()).getByRole('group', { name: 'Finding behind this risk' })).toBeInTheDocument();
    const decision = within(panel()).getByRole('group', { name: 'Review decision' });
    expect(within(decision).getByRole('button', { name: /^Approve/ })).toBeInTheDocument();
    expect(within(decision).getByRole('button', { name: /^Reject/ })).toBeInTheDocument();
    expect(within(decision).getByRole('button', { name: 'Needs clarification' })).toBeInTheDocument();
  });

  it('Draft an email: an editable draft from the risk that opens as a mailto link', async () => {
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries, rowsRespond: pricedRows }));
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_total`, { activeDocumentId: 'doc_1' });

    await screen.findByRole('grid', { name: 'Sheet LV' });
    await user.click(await within(await findPanel()).findByRole('button', { name: 'Draft an email' }));
    const dialog = await screen.findByRole('dialog', { name: 'Email about this risk' });
    const subject = within(dialog).getByRole('textbox', { name: 'Subject' });
    expect(subject).toHaveValue('Question on tender.xlsx: Arithmetic, position 01.001');
    const body = within(dialog).getByRole<HTMLTextAreaElement>('textbox', { name: 'Message' });
    expect(body.value).toContain('Quantity: 12.5');
    expect(body.value).not.toContain('EUR');

    await user.type(within(dialog).getByRole('textbox', { name: 'To' }), 'planner@example.com');
    const link = within(dialog).getByRole('link', { name: 'Open in email app' });
    expect(link.getAttribute('href')).toMatch(/^mailto:planner@example\.com\?subject=Question%20on%20tender\.xlsx/);
    expect(within(dialog).getByRole('button', { name: 'Copy email' })).toBeInTheDocument();
  });

  it('Approve records the decision on the finding and opens the cell for editing', async () => {
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
          { path: '/api/v1/collaboration/issues/iss_1/comments', respond: {
            items: [], task: { assignee: 'johan', status: 'waiting', task_type: 'check', due_date: '2026-12-03' },
          } },
        ],
      }),
    );
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_total`, { activeDocumentId: 'doc_1' });

    const decision = await within(await findPanel()).findByRole('group', { name: 'Review decision' });
    await screen.findByRole('grid', { name: 'Sheet LV' });
    await user.click(within(decision).getByRole('button', { name: /^Approve/ }));
    await waitFor(() => expect(api.callsTo('POST', '/api/v1/issues/iss_1/review')).toHaveLength(1));
    expect(JSON.parse(api.callsTo('POST', '/api/v1/issues/iss_1/review')[0].body)).toEqual({
      status: 'confirmed_error',
      expected_version: 1,
    });
    expect(await within(panel()).findByText(/^Approved on /)).toBeInTheDocument();
    const editor = await within(screen.getByRole('grid', { name: 'Sheet LV' })).findByRole('textbox');
    expect(editor).toHaveAccessibleName(/^Edit /);
    expect(editor).toHaveFocus();
    expect(api.callsTo('PUT', '/api/v1/collaboration/issues/iss_1/task')).toHaveLength(0);
    expect(within(panel()).getByRole('spinbutton', { name: /^year/ })).toHaveTextContent('2026');
  });

  it('A risk without a finding: Needs clarification and Reject are saved as its review', async () => {
    const saved: { status: string; comment: string }[] = [];
    const api = mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [
          { method: 'POST', path: '/api/v1/projects/prj_1/clarifications', respond: { clarification_id: 'clr_1' } },
          {
            method: 'PUT',
            path: `${RISK_REVIEWS}/risk_soil`,
            respond: (call) => {
              const body = JSON.parse(call.body);
              saved.push(body);
              return { risk_id: 'risk_soil', status: body.status, comment: body.comment, reviewed_at: '2026-11-21T12:05:00Z', run_id: 'run_2' };
            },
          },
        ],
      }),
    );
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_soil`, { activeDocumentId: 'doc_1' });

    const decision = await within(await findPanel()).findByRole('group', { name: 'Review decision' });
    expect(within(panel()).getByText('Which soil class applies to 01?')).toBeInTheDocument();
    expect(within(panel()).getByRole('button', { name: 'Copy question' })).toBeInTheDocument();
    await user.click(within(decision).getByRole('button', { name: 'Add a note' }));
    await user.type(within(decision).getByRole('textbox', { name: 'Note (optional)' }), 'Asked on site');
    await user.click(within(decision).getByRole('button', { name: 'Needs clarification' }));
    await waitFor(() => expect(saved).toEqual([{ status: 'in_review', comment: 'Asked on site' }]));
    expect(await within(panel()).findByText(/^In review: waiting for clarification since /)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^Risks/ })).toHaveTextContent('3');

    await user.click(within(decision).getByRole('button', { name: /^Reject/ }));
    await waitFor(() => expect(saved).toHaveLength(2));
    expect(saved[1]).toEqual({ status: 'rejected', comment: '' });
    expect(await within(panel()).findByText(/^Rejected on /)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^Risks/ })).toHaveTextContent('2');
    expect(api.callsTo('GET', RISK_REVIEWS).length).toBeGreaterThan(0);

    await user.click(within(decision).getByRole('button', { name: 'Undo decision' }));
    await waitFor(() => expect(saved).toHaveLength(3));
    expect(saved[2]).toEqual({ status: 'open', comment: '' });
    expect(await within(decision).findByRole('button', { name: /^Approve/ })).toBeInTheDocument();
  });

  it('Risks: search, filters, server sort, the record switch and the questions for the client', async () => {
    const api = mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries }));
    const { user, location } = renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });

    const list = await screen.findByRole('list', { name: 'Risks' });
    const names = () => within(screen.getByRole('list', { name: 'Risks' })).getAllByRole('button').map((row) => row.dataset.riskId);
    expect(names()).toEqual(['risk_total', 'risk_price', 'risk_soil']);
    expect(within(panel()).getByText('Showing 3 of 3 risks.')).toBeInTheDocument();

    await user.type(within(panel()).getByRole('searchbox', { name: 'Search the risks' }), 'soil');
    expect(names()).toEqual(['risk_soil']);
    await user.click(within(panel()).getByRole('button', { name: 'Clear filters' }));
    expect(names()).toHaveLength(3);

    await user.click(within(panel()).getByRole('button', { name: 'Filters' }));
    await chooseOption(user, 'Priority', 'High', panel());
    expect(names()).toEqual(['risk_total']);
    await user.click(within(panel()).getByRole('button', { name: 'Clear filters' }));
    await chooseOption(user, 'Classification', 'Ambiguity', panel());
    expect(names()).toEqual(['risk_soil']);
    await user.click(within(panel()).getByRole('button', { name: 'Clear filters' }));

    const status = within(panel()).getByRole('group', { name: 'Status' });
    expect(within(status).getAllByRole('button').map((chip) => chip.textContent)).toEqual([
      'All 3',
      'Open 3',
      'In review 0',
      'Approved 0',
      'Rejected 0',
    ]);
    await user.click(within(panel()).getByRole('checkbox', { name: 'Show 1 kept reminder' }));
    expect(names()).toHaveLength(4);

    await chooseOption(user, 'Sort by', 'Money at stake', panel());
    await waitFor(() => expect(api.callsTo('GET', RISKS).some((call) => call.query.get('sort_by') === 'price_impact')).toBe(true));

    await user.click(within(panel()).getByRole('button', { name: /Questions for the client/ }));
    expect(within(panel()).getByRole('button', { name: 'Copy all questions' })).toBeInTheDocument();

    await user.click(within(list).getByRole('button', { name: /Soil class of 01/ }));
    await waitFor(() => expect(location()).toContain('risk=risk_soil'));
  });

  it('uses the same overdue rule for risk summaries and filtering, including historical Done tasks', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 10, 21, 12));
    try {
      const cases = [
        { assignee: 'johan', due_date: '2026-11-20', status: 'done' },
        { assignee: 'johan', due_date: '2026-11-20', status: 'waiting' },
        { assignee: null, due_date: '2026-11-20', status: 'todo' },
        { assignee: 'johan', due_date: null, status: 'todo' },
        { assignee: 'johan', due_date: '2026-11-21', status: 'todo' },
        { assignee: 'johan', due_date: '2026-11-22', status: 'todo' },
      ];
      mockFetch(projectWorkspaceRoutes({
        runs: () => runSummaries,
        report: {
          ...riskReport,
          risks: cases.map((_, index) => ({
            ...riskReport.risks[0], risk_id: `risk_${index}`, source_issue_ids: [`task_${index}`],
          })),
        },
        extra: [{ path: '/api/v1/collaboration/validation-runs/run_2/tasks', respond: {
          items: cases.map((task, index) => ({ ...task, issue_id: `task_${index}`, assignee_name: task.assignee ? 'Johan' : null })),
        } }],
      }));
      const { user } = renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });
      const list = await screen.findByRole('list', { name: 'Risks' });
      await waitFor(() => expect(within(list).getAllByText(/^Overdue:/)).toHaveLength(2));
      const riskRows = within(list).getAllByRole('button');
      expect(riskRows).toHaveLength(6);
      for (const [index, row] of riskRows.entries()) {
        expect(Boolean(within(row).queryByText(/^Overdue:/))).toBe(index < 2);
      }
      await user.click(within(panel()).getByRole('button', { name: 'Filters' }));
      await user.click(within(panel()).getByRole('checkbox', { name: 'Overdue tasks only' }));
      expect(within(list).getAllByRole('button')).toEqual(riskRows.slice(0, 2));
      await user.click(within(panel()).getByRole('checkbox', { name: 'Overdue tasks only' }));
      expect(within(list).getAllByRole('button')).toHaveLength(6);
    } finally {
      vi.useRealTimers();
    }
  });

  it('Risks: J and K move between risks, R rejects, Esc goes back to the list', async () => {
    const rejected = {
      ...lineTotalIssue,
      review_status: 'false_positive',
      version: 2,
      reviewed_at: '2026-11-21T12:05:00Z',
      allowed_review_actions: ['pending_review', 'confirmed_error', 'needs_more_information'],
    };
    const api = mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [{ method: 'POST', path: '/api/v1/issues/iss_1/review', respond: { issue: rejected, history: issueHistory } }],
      }),
    );
    const { user, location } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_total`, { activeDocumentId: 'doc_1' });

    expect(await within(await findPanel()).findByText('Risk 1 of 3')).toBeInTheDocument();
    within(panel()).getByRole('button', { name: 'All risks' }).focus();
    await user.keyboard('j');
    await waitFor(() => expect(location()).toContain('risk=risk_price'));
    expect(within(panel()).getByText('Risk 2 of 3')).toBeInTheDocument();
    await user.keyboard('k');
    await waitFor(() => expect(location()).toContain('risk=risk_total'));

    await user.keyboard('r');
    await waitFor(() => expect(api.callsTo('POST', '/api/v1/issues/iss_1/review')).toHaveLength(1));
    expect(JSON.parse(api.callsTo('POST', '/api/v1/issues/iss_1/review')[0].body).status).toBe('false_positive');
    expect(await within(panel()).findByText(/^Rejected on /)).toBeInTheDocument();
    expect(within(panel()).getByRole('button', { name: 'Next risk' })).toBeInTheDocument();

    within(panel()).getByRole('button', { name: 'All risks' }).focus();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(location()).not.toContain('risk='));
    expect(await screen.findByRole('list', { name: 'Risks' })).toBeInTheDocument();
  });

  it('Risks: a decision keeps the list the reviewer steps through, and keys work after a click', async () => {
    const rejected = {
      ...lineTotalIssue,
      review_status: 'false_positive',
      version: 2,
      reviewed_at: '2026-11-21T12:05:00Z',
      allowed_review_actions: ['pending_review', 'confirmed_error', 'needs_more_information'],
    };
    const api = mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [{ method: 'POST', path: '/api/v1/issues/iss_1/review', respond: { issue: rejected, history: issueHistory } }],
      }),
    );
    const { user, location } = renderApp(`${WORKSPACE_URL}&tab=risks&status=open`, { activeDocumentId: 'doc_1' });

    const list = await screen.findByRole('list', { name: 'Risks' });
    await user.click(within(list).getAllByRole('button')[0]);
    expect(await within(panel()).findByText('Risk 1 of 3')).toBeInTheDocument();
    // No focus step: the keys reach the tab right after the click.
    await user.keyboard('r');
    await waitFor(() => expect(api.callsTo('POST', '/api/v1/issues/iss_1/review')).toHaveLength(1));
    expect(await within(panel()).findByText(/^Rejected on /)).toBeInTheDocument();
    // The rejected risk left the Open filter; the counter and the arrows still follow it.
    expect(within(panel()).getByText('Risk 1 of 3')).toBeInTheDocument();
    expect(within(panel()).getByRole('button', { name: 'Next risk in the list' })).toBeEnabled();

    await user.click(within(panel()).getByRole('button', { name: 'Next risk' }));
    await waitFor(() => expect(location()).toContain('risk=risk_price'));
    expect(within(panel()).getByText('Risk 2 of 3')).toBeInTheDocument();
  });

  it('Risks: whose risks to show, from the tasks on their findings', async () => {
    const task = { issue_id: 'iss_1', assignee: 'larissa', assignee_name: 'Larissa', status: 'todo', task_type: null, due_date: null };
    mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [
          {
            method: 'GET',
            path: '/api/v1/collaboration/session',
            respond: { reviewer: { handle: 'larissa', name: 'Larissa' }, reviewers: [{ handle: 'larissa', name: 'Larissa' }, { handle: 'amin', name: 'Amin' }] },
          },
          { method: 'GET', path: /^\/api\/v1\/collaboration\/validation-runs\/[^/]+\/tasks$/, respond: { items: [task] } },
          { method: 'GET', path: '/api/v1/collaboration/issues/iss_1/comments', respond: { items: [], task } },
          { method: 'GET', path: '/api/v1/collaboration/notifications', respond: { items: [], unread_count: 0 } },
        ],
      }),
    );
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });

    await screen.findByRole('list', { name: 'Risks' });
    const names = () => within(screen.getByRole('list', { name: 'Risks' })).getAllByRole('button').map((row) => row.dataset.riskId);
    await waitFor(() => expect(within(panel()).getByText(/Assigned to Larissa/)).toBeInTheDocument());
    await chooseOption(user, 'Assigned to', 'Assigned to me', panel());
    expect(names()).toEqual(['risk_total']);
    await chooseOption(user, 'Assigned to', 'Unassigned', panel());
    expect(names()).toEqual(['risk_price', 'risk_soil']);
  });

  it('Risks: downloads of the results closed under the list, also from old tab links', async () => {
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries }));
    const { user } = renderApp(`${WORKSPACE_URL}&tab=export`, { activeDocumentId: 'doc_1' });

    await user.click(await within(await findPanel()).findByRole('button', { name: 'Downloads and earlier validations' }));
    expect(within(panel()).getByRole('region', { name: 'Download the results' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^Risks/ })).toHaveAttribute('aria-selected', 'true');
    expect(within(panel()).getByRole('button', { name: 'Download table as Excel' })).toBeInTheDocument();
  });

  it('Risks: the local model\'s two actions at the end, once a model is set up; Properties says nothing of the checking', async () => {
    const llm = { provider: 'ollama', model: 'qwen', ready: true, reason: null };
    mockFetch([{ path: '/api/v1/health', respond: { ...DEFAULT_HEALTH, llm } }, ...projectWorkspaceRoutes({ runs: () => runSummaries })]);
    const { user } = renderApp(`${WORKSPACE_URL}&tab=insights`, { activeDocumentId: 'doc_1' });

    // The old AI Risk Insights link opens Risks.
    await within(await findPanel()).findByRole('list', { name: 'Risks' });
    expect(screen.getByRole('tab', { name: /^Risks/ })).toHaveAttribute('aria-selected', 'true');
    const model = within(panel()).getByRole('region', { name: 'Language model' });
    expect(within(model).getByRole('button', { name: 'Look for more risks with the local model' })).toBeInTheDocument();
    expect(within(model).getByRole('button', { name: 'Match materials with the local model and validate' })).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Properties' }));
    expect(within(panel()).queryByRole('button', { name: 'How the bill was checked' })).not.toBeInTheDocument();
    expect(within(panel()).queryByText(/doubts found in the bill/)).not.toBeInTheDocument();
  });

  it('Risks: no local model actions while no model is set up', async () => {
    const llm = { provider: 'none', model: null, ready: false, reason: 'not configured' };
    mockFetch([{ path: '/api/v1/health', respond: { ...DEFAULT_HEALTH, llm } }, ...projectWorkspaceRoutes({ runs: () => runSummaries })]);
    renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });

    await within(await findPanel()).findByRole('list', { name: 'Risks' });
    expect(within(panel()).queryByRole('region', { name: 'Language model' })).not.toBeInTheDocument();
    expect(within(panel()).queryByRole('button', { name: /local model/ })).not.toBeInTheDocument();
  });

  it('Price of the position inside a price risk, with a new price saved as a revision', async () => {
    let revision = 1;
    const api = mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        rowsRespond: pricedRows,
        extra: [
          {
            method: 'POST',
            path: '/api/v1/datasets/ds_1/corrections',
            respond: () => {
              revision = 2;
              return { dataset_id: 'ds_1', revision: 2, changed: true, corrections: [] };
            },
          },
        ],
      }),
    );
    const { user } = renderApp(`${WORKSPACE_URL}&tab=pricing&risk=risk_price`, { activeDocumentId: 'doc_1' });

    // A price risk shows its price open; the old Pricing link opens Risks.
    expect(await within(await findPanel()).findByRole('heading', { name: 'Price' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /^Risks/ })).toHaveAttribute('aria-selected', 'true');
    await user.click(within(panel()).getAllByRole('button', { name: 'Use as new price' })[0]);
    const input = within(panel()).getByRole('textbox', { name: 'New unit price in EUR' });
    expect(input).toHaveValue('16.00');
    await user.clear(input);
    await user.type(input, '41,5');
    expect(within(panel()).getByText('518.75 EUR')).toBeInTheDocument();
    // The stated line total (520.00) is not 12.5 × 40.00, so only the unit price is saved.
    expect(within(panel()).getByText(/Only the unit price is saved/)).toBeInTheDocument();

    await user.click(within(panel()).getByRole('button', { name: 'Save the new price' }));
    expect(await within(panel()).findByText('Saved as revision 2. The uploaded file stays unchanged.')).toBeInTheDocument();
    expect(revision).toBe(2);
    expect(JSON.parse(api.callsTo('POST', '/api/v1/datasets/ds_1/corrections')[0].body)).toEqual({
      expected_revision: 1,
      corrections: [{ table_id: 'tbl_1', row_id: 'row_5', column_id: 'col_price', raw_value: '41.5' }],
    });
  });

  it('A risk that is not about a price keeps the price of its position closed', async () => {
    // The soil risk, placed on the priced row 5.
    const [totalRisk, priceRisk, soilRisk] = riskReport.risks;
    const report = { ...riskReport, risks: [totalRisk, priceRisk, { ...soilRisk, positions: totalRisk.positions }] };
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries, rowsRespond: pricedRows, report }));
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_soil`, { activeDocumentId: 'doc_1' });

    await within(await findPanel()).findByRole('group', { name: 'Review decision' });
    expect(within(panel()).queryByRole('heading', { name: 'Price' })).not.toBeInTheDocument();
    const closed = await within(panel()).findByRole('button', { name: 'Price of this position' });
    expect(closed).toHaveAttribute('aria-expanded', 'false');
    await user.click(closed);
    expect(within(panel()).getByRole('textbox', { name: 'New unit price in EUR' })).toBeInTheDocument();
  });

  it('A flagged cell opens its risk in the panel, without a note on the sheet', async () => {
    mockFetch(projectWorkspaceRoutes({ runs: () => runSummaries }));
    const { user, location } = renderApp(`${WORKSPACE_URL}&tab=risks`, { activeDocumentId: 'doc_1' });

    await screen.findByRole('list', { name: 'Risks' });
    const grid = await screen.findByRole('grid', { name: 'Sheet LV' });
    const rowFive = within(grid).getAllByRole('row').find((row) => within(row).queryByRole('rowheader')?.textContent.includes('5'));
    // Row 5 is in the fixture.
    const cells = within(rowFive!).getAllByRole('gridcell');
    await user.click(cells[cells.length - 1]);
    await waitFor(() => expect(location()).toContain('risk=risk_total'));
    expect(screen.queryByRole('dialog', { name: /^Findings for cell/ })).not.toBeInTheDocument();
    expect(await within(panel()).findByRole('heading', { name: 'Arithmetic', level: 2 })).toBeInTheDocument();
  });
});
