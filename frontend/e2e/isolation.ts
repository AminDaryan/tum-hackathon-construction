/**
 * What keeps the browser test apart from the shell it runs in and from other checkouts: the
 * environment of the test backend and the default output folder. No side effects on import, so
 * the unit tests (e2e/backend-launcher.test.ts) can load it.
 */
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/**
 * Operating-system variables the test backend may inherit, compared without regard to case
 * (Windows spells them `Path`, `SystemRoot`, ...). Nothing else reaches it: no `TWB_*` setting
 * of the developer's shell (an access token, a database URL), and no Python variables such as
 * `PYTHONPATH` that would change which code the backend runs.
 */
export const INHERITED_VARIABLES = Object.freeze([
  'PATH',
  'PATHEXT',
  'HOME',
  'USERPROFILE',
  'HOMEDRIVE',
  'HOMEPATH',
  'APPDATA',
  'LOCALAPPDATA',
  'PROGRAMDATA',
  'SYSTEMROOT',
  'SYSTEMDRIVE',
  'WINDIR',
  'COMSPEC',
  'NUMBER_OF_PROCESSORS',
  'PROCESSOR_ARCHITECTURE',
  'TEMP',
  'TMP',
  'TMPDIR',
  'LANG',
  'LC_ALL',
  'LC_CTYPE',
  'TZ',
]);

const INHERITED = new Set(INHERITED_VARIABLES);

/**
 * The environment of the test backend: the operating-system variables of `inherited` (see
 * {@link INHERITED_VARIABLES}) and the settings the test sets, which win.
 *
 * @param inherited the launcher's own environment
 * @param settings what the test sets, e.g. `TWB_DATA_DIR`
 */
export function backendEnvironment(
  inherited: Record<string, string | undefined>,
  settings: Record<string, unknown>,
): Record<string, string> {
  const environment: Record<string, string> = {};
  for (const [name, value] of Object.entries(inherited)) {
    if (typeof value === 'string' && INHERITED.has(name.toUpperCase())) environment[name] = value;
  }
  for (const [name, value] of Object.entries(settings)) {
    if (typeof value !== 'string') throw new TypeError(`The backend setting ${name} must be a string.`);
    environment[name] = value;
  }
  return environment;
}

/**
 * Playwright's output folder: `TWB_E2E_OUTPUT_DIR` when set (CI sets it), else a folder in the
 * system's temporary directory named after a short hash of this checkout's frontend directory,
 * so test runs of two checkouts on one machine never share (and empty) one folder.
 *
 * @param base the temporary directory
 */
export function outputDirFor(
  environment: Record<string, string | undefined>,
  frontendDir: string,
  base: string = tmpdir(),
): string {
  if (environment.TWB_E2E_OUTPUT_DIR) return environment.TWB_E2E_OUTPUT_DIR;
  const checkout = createHash('sha256').update(frontendDir).digest('hex').slice(0, 10);
  return join(base, `twb-e2e-results-${checkout}`);
}
