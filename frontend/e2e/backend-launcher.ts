/**
 * Starts the browser test's backend with a clean environment (`node e2e/backend-launcher.ts`,
 * the first web server of playwright.config.ts).
 *
 * Playwright starts every web server with its own environment merged into `webServer.env`, so a
 * `TWB_AUTH__TOKENS` or `TWB_DATABASE_URL` in the developer's shell would reach the backend and
 * change what the test checks. This launcher runs the backend command with only the settings
 * the test sets plus the operating-system variables a process needs (e2e/isolation.ts), never
 * an inherited `TWB_*` value. It needs no shell quoting, so it works the same on every system.
 *
 *   TWB_E2E_BACKEND_COMMAND   JSON array: the program and its arguments (uvicorn ...)
 *   TWB_E2E_BACKEND_SETTINGS  JSON object of strings: the backend's settings (TWB_DATA_DIR, ...)
 *
 * The launcher passes SIGINT and SIGTERM on to the backend and exits with its exit code.
 */
import { spawn } from 'node:child_process';
import { backendEnvironment } from './isolation.ts';

function parsed<T>(name: string, check: (value: unknown) => value is T, expected: string): T {
  let value: unknown;
  try {
    value = JSON.parse(process.env[name] ?? '');
  } catch {
    value = undefined;
  }
  if (!check(value)) {
    console.error(`backend-launcher: ${name} must be ${expected}.`);
    process.exit(2);
  }
  return value;
}

const command = parsed(
  'TWB_E2E_BACKEND_COMMAND',
  (value): value is string[] => Array.isArray(value) && value.length > 0 && value.every((part) => typeof part === 'string'),
  'a JSON array of strings (the program and its arguments)',
);
const settings = parsed(
  'TWB_E2E_BACKEND_SETTINGS',
  (value): value is Record<string, string> =>
    value !== null && typeof value === 'object' && !Array.isArray(value) && Object.values(value).every((item) => typeof item === 'string'),
  'a JSON object of strings',
);

const [program, ...args] = command;
const backend = spawn(program, args, { env: backendEnvironment(process.env, settings), stdio: 'inherit' });

for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => backend.kill(signal));
}
backend.on('error', (error) => {
  console.error(`backend-launcher: could not start ${program}: ${error.message}`);
  process.exit(1);
});
backend.on('exit', (code, signal) => {
  process.exit(code ?? (signal ? 1 : 0));
});
