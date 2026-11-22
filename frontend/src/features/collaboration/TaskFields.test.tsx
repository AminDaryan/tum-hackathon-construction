import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { applyLanguage, t } from '../../i18n/messages.ts';
import type { FindingTask, TaskInput } from '../../services/apiTypes.ts';
import { errorResponse, mockFetch } from '../../test/fetchMock.ts';
import { chooseOption, getSelect } from '../../test/select.ts';
import { AssistantExtras } from './AssistantExtras.tsx';
import { CollaborationProvider } from './CollaborationProvider.tsx';
import { FindingComments } from './FindingComments.tsx';
import { TaskFields } from './TaskFields.tsx';
import { TaskSummary } from './TaskSummary.tsx';

const savedTask: TaskInput = { assignee: 'johan', status: 'done', task_type: 'check', due_date: '2026-12-03' };
const reviewers = [{ handle: 'johan', name: 'Johan' }, { handle: 'larissa', name: 'Larissa' }];

afterEach(() => applyLanguage('en'));

it.each(['en', 'de'])('shows owner, type and date without task progress in %s', (language) => {
  applyLanguage(language);
  render(<>
    <TaskFields task={savedTask} reviewers={reviewers} isDisabled={false} onSave={vi.fn()} />
    <TaskSummary task={{ ...savedTask, assignee_name: 'Johan' } as FindingTask} />
  </>);
  const task = screen.getByRole('group', { name: t('Task') });
  expect(getSelect(t('Assignee'), task)).toHaveTextContent('Johan');
  expect(getSelect(t('Type'), task)).toHaveTextContent(t('Check'));
  expect(within(task).getByRole('button', { name: new RegExp(`^${t('Choose due date')}`) })).toBeEnabled();
  expect(screen.getByText(t('Assigned to {name}', { name: 'Johan' }))).toBeInTheDocument();
  for (const label of ['Status', 'To do', 'In progress', 'Waiting', 'Done']) {
    expect(screen.queryByText(t(label), { exact: true })).not.toBeInTheDocument();
  }
});

it.each(['todo', 'in_progress', 'waiting', 'done'] as const)('changes and clears the assignee while preserving %s and the deadline', async (status) => {
  const user = userEvent.setup();
  let task = { ...savedTask, status };
  mockFetch([
    { path: '/api/v1/collaboration/session', respond: { reviewer: reviewers[0], reviewers } },
    { path: '/api/v1/collaboration/notifications', respond: { items: [], unread_count: 0 } },
    { path: '/api/v1/collaboration/issues/finding-1/comments', respond: () => ({ items: [], task }) },
    { method: 'PUT', path: '/api/v1/collaboration/issues/finding-1/task', respond: (call) => {
      task = JSON.parse(call.body);
      return { task };
    } },
  ]);
  render(<MemoryRouter><CollaborationProvider><FindingComments issueId="finding-1" /></CollaborationProvider></MemoryRouter>);
  await waitFor(() => expect(getSelect('Assignee')).toBeEnabled());
  await chooseOption(user, 'Assignee', 'Larissa');
  await waitFor(() => expect(getSelect('Assignee')).toHaveTextContent('Larissa'));
  expect(task).toEqual({ ...savedTask, status, assignee: 'larissa' });
  await chooseOption(user, 'Assignee', 'Unassigned');
  await waitFor(() => expect(getSelect('Assignee')).toHaveTextContent('Unassigned'));
  expect(task).toEqual({ ...savedTask, status, assignee: null });
});

it.each(['assignee', 'date', 'clear date'])('reports a failed %s save while comments are collapsed', async (field) => {
  const user = userEvent.setup();
  const api = mockFetch([
    { path: '/api/v1/collaboration/session', respond: { reviewer: reviewers[0], reviewers } },
    { path: '/api/v1/collaboration/notifications', respond: { items: [], unread_count: 0 } },
    { path: '/api/v1/collaboration/issues/finding-1/comments', respond: { items: [], task: savedTask } },
    { method: 'PUT', path: '/api/v1/collaboration/issues/finding-1/task', respond: errorResponse(503, 'unavailable', 'Task could not be saved.') },
  ]);
  render(<MemoryRouter><CollaborationProvider><FindingComments issueId="finding-1" /></CollaborationProvider></MemoryRouter>);
  await waitFor(() => expect(getSelect('Assignee')).toBeEnabled());
  if (field === 'assignee') await chooseOption(user, 'Assignee', 'Larissa');
  else if (field === 'clear date') await user.click(screen.getByRole('button', { name: 'Clear due date' }));
  else {
    await user.click(screen.getByRole('button', { name: /^Choose due date/ }));
    await user.click(await screen.findByRole('button', { name: /December 15, 2026/ }));
  }
  expect(await screen.findByRole('alert')).toHaveTextContent('Task could not be saved.');
  expect(JSON.parse(api.callsTo('PUT', '/api/v1/collaboration/issues/finding-1/task')[0].body).status).toBe('done');
  expect(getSelect('Assignee')).toHaveTextContent('Johan');
  expect(screen.getByRole('button', { name: 'Clear due date' })).toBeEnabled();
});

it('keeps assistant status and assignment actions available', async () => {
  const user = userEvent.setup();
  const onTask = vi.fn();
  render(<AssistantExtras reviewers={reviewers} onTask={onTask} extras={{
    email_draft: null,
    next_steps: [
      { label: 'Start checking', action: 'set_status', status: 'in_progress' },
      { label: 'Delegate', action: 'assign', assignee: 'larissa' },
    ],
  }} />);
  await user.click(screen.getByRole('button', { name: 'Start checking: set status to In progress' }));
  expect(onTask).toHaveBeenLastCalledWith({ status: 'in_progress' });
  await user.click(screen.getByRole('button', { name: 'Delegate: assign Larissa' }));
  expect(onTask).toHaveBeenLastCalledWith({ assignee: 'larissa' });
});
