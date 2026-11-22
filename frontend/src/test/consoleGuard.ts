/**
 * Test guard: every console.error call (React warnings, unmatched fetch routes) is recorded, and a test that wrote any fails.
 */
import { format } from 'node:util';

const recorded: string[] = [];

/** Replaces console.error with the recorder. Called once from the setup file. */
export function installConsoleGuard() {
  console.error = (...args: unknown[]) => {
    recorded.push(format(...args));
  };
}

/**
 * Removes and returns every recorded message.
 */
export function takeConsoleErrors(): string[] {
  return recorded.splice(0, recorded.length);
}
