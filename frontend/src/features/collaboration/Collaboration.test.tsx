import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { mockFetch } from '../../test/fetchMock.ts';
import { CollaborationProvider } from './CollaborationProvider.tsx';
import { FindingComments } from './FindingComments.tsx';
import { TaskSummary } from './TaskSummary.tsx';
import type { FindingTask, TaskStatus } from '../../services/apiTypes.ts';

it('emphasises known mentions without changing comment text or highlighting unknown words and email addresses', async () => {
  const body = '@Johan, please ask (@decivio).\n@unknown @johan_extra mail@johan @@johan é@johan @johan';
  mockFetch([
    {
      path: '/api/v1/collaboration/session',
      respond: { reviewer: null, reviewers: [{ handle: 'johan', name: 'Johan' }] },
    },
    {
      path: '/api/v1/collaboration/issues/finding-1/comments',
      respond: {
        items: [{
          comment_id: 'comment-1',
          author: 'johan',
          author_name: 'Johan',
          body,
          created_at: '2026-11-21T12:00:00Z',
        }],
      },
    },
  ]);
  render(
    <MemoryRouter initialEntries={['/?comment=comment-1']}>
      <CollaborationProvider>
        <FindingComments issueId="finding-1" />
      </CollaborationProvider>
    </MemoryRouter>,
  );
  const thread = screen.getByRole('region', { name: 'Finding comments' });
  const message = (await within(thread).findByText('@Johan')).closest('p')!;
  expect(message.textContent).toBe(body);
  const mentions = [...message.querySelectorAll('span')];
  expect(mentions.map((node) => node.textContent)).toEqual(['@Johan', '@decivio', '@johan']);
  for (const mention of mentions) expect(mention).toHaveClass('text-accent', 'font-semibold');
});

it.each<[string | null, TaskStatus, string | null, boolean]>([
  ['2026-11-20', 'waiting', 'johan', true],
  ['2026-11-21', 'todo', 'johan', false],
  ['2026-11-22', 'in_progress', 'johan', false],
  ['2026-11-20', 'done', 'johan', true],
  ['2026-11-20', 'todo', null, false],
  [null, 'todo', 'johan', false],
])('shows deadline %s for status %s and assignee %s with overdue=%s', (due_date, status, assignee, overdue) => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 10, 21, 12));
  try {
    const { container } = render(<TaskSummary task={{ status, due_date, assignee } as FindingTask} />);
    const deadline = container.querySelector('time');
    if (!due_date) expect(deadline).toBeNull();
    else {
      expect(deadline).toHaveAttribute('datetime', due_date);
      expect(deadline?.textContent?.startsWith('Overdue:')).toBe(overdue);
      expect(deadline?.classList.contains('text-danger')).toBe(overdue);
    }
    for (const label of ['To do', 'In progress', 'Waiting', 'Done']) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  } finally {
    vi.useRealTimers();
  }
});

it.each(['todo', 'in_progress', 'waiting', 'done'])('sets and clears a calendar date without losing stored status %s', async (status) => {
  const user = userEvent.setup();
  let task = { assignee: 'johan', status, task_type: 'ask_client', due_date: '2026-12-03' };
  mockFetch([
    { path: '/api/v1/collaboration/session', respond: {
      reviewer: { handle: 'johan', name: 'Johan' }, reviewers: [{ handle: 'johan', name: 'Johan' }],
    } },
    { path: '/api/v1/collaboration/notifications', respond: { items: [], unread_count: 0 } },
    { path: '/api/v1/collaboration/issues/finding-1/comments', respond: () => ({ items: [], task }) },
    { method: 'PUT', path: '/api/v1/collaboration/issues/finding-1/task', respond: (call) => {
      task = JSON.parse(call.body);
      return { task };
    } },
  ]);
  render(<MemoryRouter><CollaborationProvider><FindingComments issueId="finding-1" /></CollaborationProvider></MemoryRouter>);
  const trigger = await screen.findByRole('button', { name: /^Choose due date/ });
  await waitFor(() => expect(trigger).toBeEnabled());
  await user.click(trigger);
  await user.click(await screen.findByRole('button', { name: /December 15, 2026/ }));
  await waitFor(() => expect(task).toEqual({ assignee: 'johan', status, task_type: 'ask_client', due_date: '2026-12-15' }));
  await user.click(await screen.findByRole('button', { name: 'Clear due date' }));
  await waitFor(() => expect(task).toEqual({ assignee: 'johan', status, task_type: 'ask_client', due_date: null }));
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Clear due date' })).not.toBeInTheDocument());
});

it('saves a typed due date only once its year is whole and flags a short year', async () => {
  const user = userEvent.setup();
  let task = { assignee: 'johan', status: 'waiting', task_type: 'ask_client', due_date: null };
  const sent: unknown[] = [];
  mockFetch([
    { path: '/api/v1/collaboration/session', respond: {
      reviewer: { handle: 'johan', name: 'Johan' }, reviewers: [{ handle: 'johan', name: 'Johan' }],
    } },
    { path: '/api/v1/collaboration/notifications', respond: { items: [], unread_count: 0 } },
    { path: '/api/v1/collaboration/issues/finding-1/comments', respond: () => ({ items: [], task }) },
    { method: 'PUT', path: '/api/v1/collaboration/issues/finding-1/task', respond: (call) => {
      task = JSON.parse(call.body);
      sent.push(task.due_date);
      return { task };
    } },
  ]);
  render(<MemoryRouter><CollaborationProvider><FindingComments issueId="finding-1" /></CollaborationProvider></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole('button', { name: /^Choose due date/ })).toBeEnabled());
  await user.click(screen.getByRole('spinbutton', { name: /^month/ }));
  await user.keyboard('121826');
  await user.tab();
  expect(await screen.findByText('Enter a date between 2000 and 2100.')).toBeInTheDocument();
  expect(sent).toEqual([]);

  await user.click(screen.getByRole('spinbutton', { name: /^year/ }));
  await user.keyboard('2026');
  await waitFor(() => expect(sent).toEqual(['2026-12-18']));
});

it("opens Desvio's email draft in the shared editor and marks its clarification sent", async () => {
  const marked: unknown[] = [];
  mockFetch([
    { path: '/api/v1/collaboration/session', respond: { reviewer: null, reviewers: [] } },
    {
      path: '/api/v1/collaboration/issues/finding-1/comments',
      respond: {
        items: [{
          comment_id: 'comment-2',
          author: 'desvio',
          author_name: 'Desvio',
          body: 'I drafted an email to the bidder.',
          created_at: '2026-11-21T12:00:00Z',
          assistant: {
            email_draft: { to: '', recipient: 'bidder', subject: 'Pipe line total', body: 'Dear bidder, 10 m at 7 is 70.' },
            next_steps: [{ label: 'Send the email', action: 'open_email' }],
            clarification: {
              project_id: 'prj_1',
              clarification_id: 'clr_1',
              document_id: 'doc_1',
              risk_id: 'risk_pipe',
              tier: 'high',
              issue_id: 'finding-1',
              title: 'Line total does not match',
            },
          },
        }],
      },
    },
    {
      method: 'POST',
      path: '/api/v1/projects/prj_1/clarifications/emails',
      respond: (call) => {
        marked.push(JSON.parse(call.body));
        return {};
      },
    },
  ]);
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/?comment=comment-2']}>
      <CollaborationProvider>
        <FindingComments issueId="finding-1" />
      </CollaborationProvider>
    </MemoryRouter>,
  );
  const draft = await screen.findByRole('region', { name: 'Email draft' });
  expect(draft).toHaveTextContent("Listed in the project's Clarifications");
  // The suggested step opens the same draft.
  expect(screen.getByRole('button', { name: 'Send the email' })).toBeInTheDocument();
  await user.click(within(draft).getByRole('button', { name: 'Open the draft' }));
  const dialog = await screen.findByRole('dialog', { name: 'Email draft' });
  await user.type(within(dialog).getByRole('textbox', { name: 'To' }), 'bidder@example.com');
  const open = within(dialog).getByRole('link', { name: 'Open in email app' });
  expect(open.getAttribute('href')).toMatch(/^mailto:bidder@example\.com\?subject=Pipe%20line%20total/);
  open.addEventListener('click', (event) => event.preventDefault()); // jsdom cannot open mailto:
  await user.click(open);
  await waitFor(() =>
    expect(marked).toEqual([
      {
        document_id: 'doc_1',
        risk_id: 'risk_pipe',
        tier: 'high',
        title: 'Line total does not match',
        issue_id: 'finding-1',
        recipient: 'bidder@example.com',
        subject: 'Pipe line total',
        body: 'Dear bidder, 10 m at 7 is 70.',
        sent: true,
      },
    ]),
  );
});

it('closes the mention suggestions on Escape and once the text has no @ to complete', async () => {
  mockFetch([
    {
      path: '/api/v1/collaboration/session',
      respond: {
        reviewer: { handle: 'imants', name: 'Imants' },
        reviewers: [{ handle: 'imants', name: 'Imants' }, { handle: 'larissa', name: 'Larissa' }],
      },
    },
    { path: '/api/v1/collaboration/issues/finding-1/comments', respond: { items: [] } },
    { path: '/api/v1/collaboration/notifications', respond: { items: [], unread: 0 } },
  ]);
  const user = userEvent.setup();
  render(
    <MemoryRouter initialEntries={['/?comment=open']}>
      <CollaborationProvider>
        <FindingComments issueId="finding-1" />
      </CollaborationProvider>
    </MemoryRouter>,
  );
  const box = await screen.findByRole('textbox', { name: 'Comment as Imants' });
  await user.type(box, '@la');
  expect(within(screen.getByRole('list', { name: 'Mention suggestions' })).getByRole('button')).toHaveTextContent('Larissa @larissa');

  await user.clear(box);
  expect(screen.queryByRole('list', { name: 'Mention suggestions' })).not.toBeInTheDocument();

  await user.type(box, '@la');
  expect(screen.getByRole('list', { name: 'Mention suggestions' })).toBeInTheDocument();
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('list', { name: 'Mention suggestions' })).not.toBeInTheDocument();
  expect(box).toHaveValue('@la');

  // Typing on asks again.
  await user.type(box, 'r');
  expect(screen.getByRole('list', { name: 'Mention suggestions' })).toBeInTheDocument();
});
