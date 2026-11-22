import { resetLocalTimeZone, setLocalTimeZone } from '@internationalized/date';
import { afterEach, expect, it, vi } from 'vitest';
import { isTaskOverdue } from './tasks.ts';

afterEach(() => {
  resetLocalTimeZone();
  vi.useRealTimers();
});

it.each([
  ['America/Los_Angeles', '2026-11-20', true],
  ['America/Los_Angeles', '2026-11-21', false],
  ['Europe/Berlin', '2026-11-21', true],
  ['Europe/Berlin', '2026-11-22', false],
])('uses the local calendar in %s for deadline %s', (zone, due_date, overdue) => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-11-22T00:30:00Z'));
  setLocalTimeZone(zone);
  expect(isTaskOverdue({ assignee: 'johan', due_date })).toBe(overdue);
});

it('does not mark missing tasks, assignees or dates overdue', () => {
  expect(isTaskOverdue(null)).toBe(false);
  expect(isTaskOverdue(undefined)).toBe(false);
  expect(isTaskOverdue({ assignee: null, due_date: '2000-01-01' })).toBe(false);
  expect(isTaskOverdue({ assignee: 'johan', due_date: null })).toBe(false);
  expect(isTaskOverdue({ assignee: 'johan' })).toBe(false);
});
