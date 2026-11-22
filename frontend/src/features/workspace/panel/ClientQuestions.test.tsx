import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { applyLanguage, t } from '../../../i18n/messages.ts';
import { ClientQuestions } from './ClientQuestions.tsx';

afterEach(() => applyLanguage('en'));

it.each(['en', 'de'] as const)('copies the displayed question and positions with %s feedback', async (language) => {
  applyLanguage(language);
  const user = userEvent.setup();
  const questions = [
    { question: 'Welche Zeichnung gilt?', positions: ['01.01', '02.02', '01.01'] },
    { question: 'Please confirm the finish.', positions: ['03.03', '04.04'] },
    { question: 'When is the deadline?' },
  ];
  const { rerender } = render(<ClientQuestions questions={questions} />);
  await user.click(screen.getByRole('button', { name: new RegExp(t('Questions for the client')) }));
  const items = screen.getAllByRole('listitem');
  for (const [index, expected] of [
    'Welche Zeichnung gilt? (01.01, 02.02)',
    'Please confirm the finish. (03.03, 04.04)',
    'When is the deadline?',
  ].entries()) {
    await user.click(within(items[index]).getByRole('button', { name: t('Copy question') }));
    expect(await navigator.clipboard.readText()).toBe(expected);
    expect(within(items[index]).getByRole('status')).toHaveTextContent(t('Copied'));
  }

  await user.click(screen.getByRole('button', { name: t('Copy all questions') }));
  expect(await navigator.clipboard.readText()).toBe(
    'Welche Zeichnung gilt? (01.01, 02.02, 01.01)\n\nPlease confirm the finish. (03.03, 04.04)\n\nWhen is the deadline?',
  );

  rerender(<ClientQuestions questions={[{ question: 'Updated question', positions: ['05.05'] }]} />);
  await user.click(screen.getByRole('button', { name: t('Copy question') }));
  expect(await navigator.clipboard.readText()).toBe('Updated question (05.05)');
});

it.each(['en', 'de'] as const)('waits for clipboard success and reports rejection in %s', async (language) => {
  applyLanguage(language);
  const user = userEvent.setup();
  let rejectWrite!: (reason: Error) => void;
  vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(() => new Promise((_, reject) => { rejectWrite = reject; }));
  render(<ClientQuestions questions={[{ question: 'Confirm?', positions: ['01'] }]} />);
  await user.click(screen.getByRole('button', { name: new RegExp(t('Questions for the client')) }));
  await user.click(screen.getByRole('button', { name: t('Copy question') }));
  const item = within(screen.getByRole('listitem'));
  expect(item.getByRole('status')).toBeEmptyDOMElement();
  await act(async () => rejectWrite(new Error('Clipboard denied')));
  expect(item.getByRole('status')).toHaveTextContent(t('The browser did not allow copying.'));
  expect(item.getByRole('button', { name: t('The browser did not allow copying.') })).toBeInTheDocument();
  expect(item.getByRole('status')).not.toHaveTextContent(t('Copied'));
});
