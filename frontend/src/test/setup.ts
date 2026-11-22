/**
 * Vitest setup: jest-dom matchers, DOM cleanup, clean localStorage and sessionStorage per test
 * and the console guard that turns unexpected console.error output into test failures.
 */
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';
import { installConsoleGuard, takeConsoleErrors } from './consoleGuard.ts';

installConsoleGuard();

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  takeConsoleErrors();
});

afterEach(() => {
  cleanup();
  const errors = takeConsoleErrors();
  if (errors.length) {
    throw new Error(`Unexpected console.error output:\n\n${errors.join('\n\n')}`);
  }
});
