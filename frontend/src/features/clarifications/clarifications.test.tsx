import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { documentSummary, runSummaries } from '../../test/fixtures.ts';
import { errorResponse, mockFetch, pendingUntilAborted } from '../../test/fetchMock.ts';
import { renderApp } from '../../test/render.tsx';
import { chooseOption } from '../../test/select.ts';
import { projectWorkspaceRoutes, RISK_REVIEWS, WORKSPACE_URL } from '../../test/workspaceRoutes.ts';
import { applyLanguage } from '../../i18n/messages.ts';
import { daysUntil, dueNote, statusText } from './clarificationModel.ts';
import type { Clarification, ClarificationItem } from '../../services/clarificationsService.ts';

vi.mock('../../ifc-demo/ModelViewer.tsx', () => {
  function ModelViewer() {
    return <div data-testid="model-viewer" />;
  }
  return { ModelViewer };
});

const TODAY = new Date(2026, 10, 21); // 21 November 2026, local time
const CUTOFF = '2026-12-03';

/** The day `offset` days from now, as the API writes it. */
function day(offset: number) {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function clarification(id: string, overrides: Partial<Clarification> = {}): Clarification {
  return {
    clarification_id: id,
    project_id: 'prj_1',
    document_id: 'doc_1',
    risk_id: 'risk_soil',
    tier: 'medium',
    kind: 'bidder_question',
    title: 'Rock layer in anchor zone: drilling method?',
    status: 'draft',
    due: null,
    phase: 'bid',
    answer: '',
    created_at: '2026-11-21T10:00:00Z',
    updated_at: '2026-11-21T10:00:00Z',
    ...overrides,
  };
}

describe('Clarification model', () => {
  const rock = clarification('clr_1', { status: 'sent', due: '2026-12-04' });
  const price = clarification('clr_2', { kind: 'subcontractor', status: 'sent', due: '2026-12-02', tier: 'high' });
  const groundwater = clarification('clr_3', { kind: 'management', status: 'sent', due: CUTOFF, tier: 'critical' });
  const answered = clarification('clr_4', { status: 'answered', due: '2026-11-24', tier: 'high' });
  const decided = clarification('clr_5', { status: 'decided', due: '2026-11-10', tier: 'critical' });

  it('words "sent" for the party asked', () => {
    expect([rock, price, groundwater, answered].map(statusText)).toEqual(['Sent', 'Waiting for reply', 'On agenda', 'Answered, not decided']);
  });

  it('counts whole local days and says how close an answer is to its day and to the cutoff', () => {
    expect(daysUntil('2026-12-04', TODAY)).toBe(13);
    expect(daysUntil('2026-11-21', new Date(2026, 10, 21, 23, 59))).toBe(0);
    expect(daysUntil(null, TODAY)).toBeNull();
    expect(dueNote(rock, CUTOFF, TODAY)).toEqual({ text: 'in 13 days', urgent: false });
    expect(dueNote(groundwater, CUTOFF, TODAY)).toEqual({ text: 'cutoff', urgent: true });
    expect(dueNote(clarification('late', { due: '2026-11-20' }), CUTOFF, TODAY)).toEqual({ text: '1 day overdue', urgent: true });
    expect(dueNote(clarification('now', { due: '2026-11-21' }), CUTOFF, TODAY)).toEqual({ text: 'today', urgent: true });
    // A decided clarification is no longer waited for, and one without a day has nothing to say.
    expect(dueNote(decided, CUTOFF, TODAY)).toBeNull();
    expect(dueNote(clarification('open'), CUTOFF, TODAY)).toBeNull();
  });

  it('speaks German when the app does', () => {
    applyLanguage('de');
    try {
      expect(dueNote(rock, CUTOFF, TODAY)).toEqual({ text: 'in 13 Tagen', urgent: false });
      expect(statusText(price)).toBe('Wartet auf Antwort');
    } finally {
      applyLanguage('en');
    }
  });
});

const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 10 };

/**
 * What the server answers for `items` (already in its order, the most urgent first): the page
 * the request asks for, after its search and filters.
 */
function pageOf(items: ClarificationItem[], query: URLSearchParams) {
  const asked = (name: string) => query.get(name) ?? '';
  const words = asked('search').toLowerCase().split(/\s+/).filter(Boolean);
  const kept = items.filter(
    (item) =>
      (!asked('phase') || item.phase === asked('phase')) &&
      (!asked('kind') || item.kind === asked('kind')) &&
      (!asked('status') || (item.clarification_id ? item.status : 'suggested') === asked('status')) &&
      (!asked('due_by') || (item.status !== 'decided' && item.due !== null && item.due <= asked('due_by'))) &&
      words.every((word) => `${item.title} ${item.recipient ?? ''}`.toLowerCase().includes(word)),
  );
  const offset = Number(asked('offset') || 0);
  const limit = Number(asked('limit') || 10);
  return { items: kept.slice(offset, offset + limit), total: kept.length, offset, limit };
}

/** A question a risk asks that nobody has raised yet, as the server lists it. */
function suggestion(riskId: string, title: string, tier = 'high'): ClarificationItem {
  return { ...clarification('unused', { risk_id: riskId, title, tier }), clarification_id: null, created_at: null, updated_at: null };
}

function project(overrides = {}) {
  return {
    project_id: 'prj_1',
    name: 'Riverside',
    description: '',
    created_at: '2026-11-21T10:00:00Z',
    status: 'in_progress',
    assignees: [],
    decision_cutoff: day(12),
    files: [{ document_id: 'doc_1', role: 'bill' }],
    demo_key: null,
    preparation: 'ready',
    preparation_error: null,
    validation: null,
    ...overrides,
  };
}

/**
 * The Follow-ups page of a project with three clarifications, in the server's order (the most
 * urgent priority first), served a page at a time; a save of the second one is kept in `saved`.
 */
function followUpsOfThree() {
  let items = [
    clarification('clr_2', { kind: 'management', title: 'Groundwater lowering, soil class unclear', status: 'sent', due: day(12), tier: 'high' }),
    clarification('clr_1', {
      status: 'sent',
      due: day(13),
      issue_id: 'iss_1',
      recipient: 'planner@example.com',
      subject: 'Question on tender.xlsx: rock layer',
      body: 'Hello, which drilling method?',
      sent_at: '2026-11-20T09:30:00Z',
    }),
    clarification('clr_3', { kind: 'subcontractor', title: 'Handover documents', phase: 'after_award' }),
  ];
  const saved: unknown[] = [];
  const api = mockFetch([
    { path: '/api/v1/projects/prj_1', respond: { project: project(), documents: [documentSummary], review_counts: {} } },
    { path: '/api/v1/projects/prj_1/clarifications', respond: (call) => pageOf(items, call.query) },
    {
      method: 'PUT',
      path: '/api/v1/clarifications/clr_1',
      respond: (call) => {
        const fields = JSON.parse(call.body);
        saved.push(fields);
        items = items.map((item) => (item.clarification_id === 'clr_1' ? { ...item, ...fields } : item));
        return items[1];
      },
    },
  ]);
  const { user } = renderApp('/projects/prj_1/follow-ups');
  const asked = () => api.callsTo('GET', '/api/v1/projects/prj_1/clarifications').at(-1)!.query.toString();
  const searches = () => api.callsTo('GET', '/api/v1/projects/prj_1/clarifications').map((call) => call.query.get('search'));
  const box = () => screen.findByRole('region', { name: /^Clarifications/ });
  // A new page is a new table: its grey rows while it loads, then its rows.
  const rows = () => within(screen.getByRole('grid', { name: /^Clarifications/ })).getAllByRole('row').slice(1);
  // The status, in the words of whoever is asked, is a control of its own in the row.
  const status = (row: HTMLElement, name: string) =>
    within(row).getByRole('button', { name: (accessibleName) => accessibleName.endsWith(`Status of ${name}`) });
  return { user, saved, asked, searches, box, rows, status };
}

describe('Clarifications of a project', () => {
  it('lists a page of the clarifications in the server\'s order, and the server searches them', async () => {
    const { user, asked, searches, box: findBox, rows, status } = followUpsOfThree();

    // On the project's Follow-ups page, as a list of its own.
    const box = await findBox();
    // The server sends one page of ten at most, of both phases until one is chosen.
    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(asked()).toBe('offset=0&limit=10');
    // No line about the cutoff above the list.
    expect(screen.queryByText(/critical or high priority/)).not.toBeInTheDocument();
    expect(rows()[0]).toHaveTextContent('ManagementGroundwater lowering, soil class uncleartender.xlsx—');
    expect(status(rows()[0], 'Groundwater lowering, soil class unclear')).toHaveAccessibleName('On agenda Status of Groundwater lowering, soil class unclear');
    expect(rows()[0]).toHaveTextContent('cutoff');
    // An email drafted about the risk: to whom and the day it was opened in the email app.
    expect(rows()[1]).toHaveTextContent('Bidder questionRock layer in anchor zone: drilling method?tender.xlsxplanner@example.com');
    expect(status(rows()[1], 'Rock layer in anchor zone: drilling method?')).toHaveAccessibleName(/^Sent Status of/);
    expect(rows()[1]).toHaveTextContent('Nov 20');
    expect(rows()[1]).toHaveTextContent('in 13 days');

    // The server searches and filters: the search reads the item, its bill and its recipient.
    const search = within(box).getByRole('searchbox', { name: 'Search clarifications' });
    await user.type(search, 'planner');
    await waitFor(() => expect(rows()).toHaveLength(1));
    // Asked once the typing stops, not once per key.
    expect(searches()).toEqual([null, 'planner']);
    expect(asked()).toBe('search=planner&offset=0&limit=10');
    expect(rows()[0]).toHaveTextContent('Rock layer in anchor zone');
    await chooseOption(user, 'Type', 'Management', box);
    expect(await within(box).findByText('No clarifications match the search and filters')).toBeInTheDocument();
    expect(asked()).toBe('search=planner&kind=management&offset=0&limit=10');
    await user.click(within(box).getByRole('button', { name: 'Clear filters' }));
    expect(search).toHaveValue('');
    await waitFor(() => expect(rows()).toHaveLength(3));
    expect(asked()).toBe('offset=0&limit=10');
  });

  it('filters the clarifications by status, due day and phase on the server', async () => {
    const { user, asked, box: findBox, rows } = followUpsOfThree();
    const box = await findBox();
    await waitFor(() => expect(rows()).toHaveLength(3));
    await chooseOption(user, 'Status', 'Sent', box);
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(asked()).toBe('status=sent&offset=0&limit=10');
    // Both answers are due in 12 and 13 days, so neither is needed within the week.
    await chooseOption(user, 'Due', 'Due this week', box);
    expect(await within(box).findByText('No clarifications match the search and filters')).toBeInTheDocument();
    expect(asked()).toBe(`status=sent&due_by=${day(7)}&offset=0&limit=10`);
    await chooseOption(user, 'Due', 'Any due date', box);
    await chooseOption(user, 'Status', 'All statuses', box);
    await waitFor(() => expect(rows()).toHaveLength(3));

    // One phase at a time when chosen.
    await chooseOption(user, 'Phase', 'After award', box);
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(asked()).toBe('phase=after_award&offset=0&limit=10');
    expect(rows()[0]).toHaveTextContent('SubcontractorHandover documents');
  });

  it('asks the server for the next ten when Next is pressed', async () => {
    const items = Array.from({ length: 12 }, (_, index) => clarification(`clr_${index + 1}`, { title: `Question ${index + 1}` }));
    const api = mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project: project(), documents: [documentSummary], review_counts: {} } },
      { path: '/api/v1/projects/prj_1/clarifications', respond: (call) => pageOf(items, call.query) },
    ]);
    const { user } = renderApp('/projects/prj_1/follow-ups');
    const box = await screen.findByRole('region', { name: /^Clarifications/ });
    const rows = () => within(within(box).getByRole('grid', { name: /^Clarifications/ })).getAllByRole('row').slice(1);
    await waitFor(() => expect(rows()).toHaveLength(10));
    expect(within(box).getByRole('heading', { name: /^Clarifications\s*\(12\)$/ })).toBeInTheDocument();

    await user.click(within(box).getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(rows()[0]).toHaveTextContent('Question 11');
    expect(api.callsTo('GET', '/api/v1/projects/prj_1/clarifications').map((call) => call.query.toString())).toEqual([
      'offset=0&limit=10',
      'offset=10&limit=10',
    ]);
  });

  it('saves the fields a row opens, and a status changed in the row', async () => {
    const { user, saved, rows, status } = followUpsOfThree();
    await waitFor(() => expect(rows()).toHaveLength(3));

    // A row opens its fields; Save replaces all of them.
    await user.click(within(rows()[1]).getByText('Rock layer in anchor zone: drilling method?'));
    const dialog = await screen.findByRole('dialog', { name: 'Clarification' });
    const email = within(dialog).getByRole('region', { name: 'Email' });
    expect(email).toHaveTextContent('Email sent Nov 20, to planner@example.comQuestion on tender.xlsx: rock layerHello, which drilling method?');
    await chooseOption(user, 'Status', 'Answered, not decided', dialog);
    await user.type(within(dialog).getByRole('textbox', { name: 'Answer' }), 'Rotary drilling');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(saved).toEqual([
        { kind: 'bidder_question', title: 'Rock layer in anchor zone: drilling method?', status: 'answered', due: day(13), phase: 'bid', answer: 'Rotary drilling' },
      ]),
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() => expect(status(rows()[1], 'Rock layer in anchor zone: drilling method?')).toHaveAccessibleName(/^Answered, not decided Status of/));

    // The status changes in the row too, saved with the rest as it is, without opening the row.
    await user.click(status(rows()[1], 'Rock layer in anchor zone: drilling method?'));
    await user.click(await screen.findByRole('option', { name: 'Decided' }));
    await waitFor(() => expect(saved).toHaveLength(2));
    expect(saved[1]).toEqual({ kind: 'bidder_question', title: 'Rock layer in anchor zone: drilling method?', status: 'decided', due: day(13), phase: 'bid', answer: 'Rotary drilling' });
    await waitFor(() => expect(status(rows()[1], 'Rock layer in anchor zone: drilling method?')).toHaveAccessibleName(/^Decided Status of/));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('lists the questions of the last validation as draft questions to the client, and saving one raises it', async () => {
    let items: ClarificationItem[] = [suggestion('risk_grade', 'Which concrete strength class applies?')];
    const raised: unknown[] = [];
    mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project: project(), documents: [documentSummary], review_counts: {} } },
      // The list loads again after the save, slowly: the saved row shows before it is back.
      { path: '/api/v1/projects/prj_1/clarifications', respond: (call) => (raised.length ? pendingUntilAborted(call) : pageOf(items, call.query)) },
      {
        method: 'POST',
        path: '/api/v1/projects/prj_1/clarifications',
        respond: (call) => {
          const body = JSON.parse(call.body);
          raised.push(body);
          items = [clarification('clr_7', { ...body, sent_at: '2026-11-21T09:30:00Z' })];
          return items[0];
        },
      },
    ]);
    const { user } = renderApp('/projects/prj_1/follow-ups');

    const table = await screen.findByRole('grid', { name: /^Clarifications/ });
    const [row] = within(table).getAllByRole('row').slice(1);
    expect(row).toHaveTextContent('Bidder questionWhich concrete strength class applies?tender.xlsx—Suggested');

    await user.click(within(row).getByText('Which concrete strength class applies?'));
    const dialog = await screen.findByRole('dialog', { name: 'Clarification' });
    // Not raised yet: nothing to save as a second one.
    expect(within(dialog).queryByRole('button', { name: 'Save as new' })).not.toBeInTheDocument();
    await chooseOption(user, 'Status', 'Sent', dialog);
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(raised).toEqual([
        {
          kind: 'bidder_question',
          title: 'Which concrete strength class applies?',
          status: 'sent',
          due: null,
          phase: 'bid',
          answer: '',
          document_id: 'doc_1',
          risk_id: 'risk_grade',
          tier: 'high',
        },
      ]),
    );
    await waitFor(() =>
      expect(within(within(table).getAllByRole('row').slice(1)[0]).getByRole('button', { name: /Status of Which concrete strength class applies\?$/ })).toHaveAccessibleName(/^Sent Status of/),
    );
    expect(within(table).getAllByRole('row').slice(1)[0]).toHaveTextContent('Nov 21');
    expect(within(table).getAllByRole('row').slice(1)).toHaveLength(1);
  });

  it('says when there are no clarifications, and saves the cutoff when its field is left', async () => {
    const patched: unknown[] = [];
    mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project: project({ decision_cutoff: null }), documents: [documentSummary], review_counts: {} } },
      { path: '/api/v1/projects/prj_1/clarifications', respond: EMPTY_PAGE },
      {
        method: 'PATCH',
        path: '/api/v1/projects/prj_1',
        respond: (call) => {
          patched.push(JSON.parse(call.body));
          return project({ decision_cutoff: '2026-12-03' });
        },
      },
    ]);
    const { user } = renderApp('/projects/prj_1/follow-ups');

    expect(await screen.findByText('No clarifications yet')).toBeInTheDocument();
    const cutoff = screen.getByLabelText('Decision cutoff');
    await user.type(cutoff, '2026-12-03');
    await user.tab();
    await waitFor(() => expect(patched).toEqual([{ decision_cutoff: '2026-12-03' }]));
  });

  it('says when the clarifications cannot be loaded, not that there are none, and Retry loads them again', async () => {
    let failing = true;
    mockFetch([
      { path: '/api/v1/projects/prj_1', respond: { project: project(), documents: [documentSummary], review_counts: {} } },
      {
        path: '/api/v1/projects/prj_1/clarifications',
        respond: () => (failing ? errorResponse(500, 'internal_error', 'Boom.') : EMPTY_PAGE),
      },
    ]);
    const { user } = renderApp('/projects/prj_1/follow-ups');

    const list = await screen.findByRole('region', { name: /^Clarifications/ });
    expect(await within(list).findByText('The clarifications could not be loaded')).toBeInTheDocument();
    expect(within(list).queryByText('No clarifications yet')).not.toBeInTheDocument();
    expect(within(list).getByRole('heading', { level: 2 })).toHaveTextContent(/^Clarifications$/);
    failing = false;
    await user.click(within(list).getByRole('button', { name: 'Retry' }));
    expect(await within(list).findByText('No clarifications yet')).toBeInTheDocument();
  });
});

describe('Needs clarification on a risk of a project bill', () => {
  it('saves the decision and lists the risk in the Clarifications of the project', async () => {
    const raised: unknown[] = [];
    mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [
          {
            method: 'PUT',
            path: `${RISK_REVIEWS}/risk_soil`,
            respond: () => ({ risk_id: 'risk_soil', status: 'in_review', comment: '', reviewed_at: '2026-11-21T12:05:00Z', run_id: 'run_2' }),
          },
          {
            method: 'POST',
            path: '/api/v1/projects/prj_1/clarifications',
            respond: (call) => {
              raised.push(JSON.parse(call.body));
              return clarification('clr_9');
            },
          },
        ],
      }),
    );
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_soil`, { activeDocumentId: 'doc_1' });

    const decision = await screen.findByRole('group', { name: 'Review decision' });
    await user.click(within(decision).getByRole('button', { name: 'Needs clarification' }));
    await waitFor(() => expect(raised).toEqual([{ document_id: 'doc_1', risk_id: 'risk_soil', tier: 'medium', title: expect.stringMatching(/Soil class of 01/) }]));
    expect(await screen.findByText('Listed in the Clarifications of the project.')).toBeInTheDocument();
  });
});

describe('An email drafted about a risk of a project bill', () => {
  it('marks the risk clarification sent when the email is opened in the email app', async () => {
    const marked: unknown[] = [];
    mockFetch(
      projectWorkspaceRoutes({
        runs: () => runSummaries,
        extra: [
          {
            method: 'POST',
            path: '/api/v1/projects/prj_1/clarifications/emails',
            respond: (call) => {
              marked.push(JSON.parse(call.body));
              return clarification('clr_9', { status: 'sent' });
            },
          },
        ],
      }),
    );
    const { user } = renderApp(`${WORKSPACE_URL}&tab=risks&risk=risk_soil`, { activeDocumentId: 'doc_1' });

    await user.click(await screen.findByRole('button', { name: 'Draft an email' }));
    const dialog = await screen.findByRole('dialog', { name: 'Email about this risk' });
    expect(dialog).toHaveTextContent("Opening or copying it marks it as sent in the project's Clarifications.");
    await user.type(within(dialog).getByRole('textbox', { name: 'To' }), 'planner@example.com');
    const open = within(dialog).getByRole('link', { name: 'Open in email app' });
    open.addEventListener('click', (event) => event.preventDefault()); // jsdom cannot open mailto:
    await user.click(open);
    await waitFor(() => expect(marked).toHaveLength(1));
    expect(marked[0]).toMatchObject({
      document_id: 'doc_1',
      risk_id: 'risk_soil',
      tier: 'medium',
      title: expect.stringMatching(/Soil class of 01/),
      recipient: 'planner@example.com',
      subject: expect.stringMatching(/^Question on /),
      body: expect.stringMatching(/^Hello,/),
      sent: true,
    });
  });
});
