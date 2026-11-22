/**
 * Unit tests of the browser test's isolation (run by vitest, not Playwright): the backend
 * launcher passes no inherited TWB_* variable on, and each checkout has its own output folder.
 */
import { spawnSync } from 'node:child_process';
import { basename, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { backendEnvironment, outputDirFor } from './isolation.ts';

const LAUNCHER = join(dirname(fileURLToPath(import.meta.url)), 'backend-launcher.ts');

/** A shell's environment as a developer might have it while running the browser test. */
const SHELL = {
  PATH: '/usr/local/bin:/usr/bin:/bin',
  HOME: '/home/reviewer',
  LANG: 'C.UTF-8',
  TWB_AUTH__TOKENS: '["a-secret-token"]',
  TWB_DATABASE_URL: 'postgresql+pg8000://postgres@db/twb',
  TWB_DATA_DIR: '/srv/twb/production-data',
  TWB_EXTRA_PROFILE_DIRS: '["/srv/profiles"]',
  PYTHONPATH: '/somewhere/else',
  VIRTUAL_ENV: '/other/venv',
  AWS_SECRET_ACCESS_KEY: 'not-for-the-backend',
};

/** Runs the real launcher with `command`; the command prints its environment as JSON. */
function launch(extra = {}, settings: Record<string, string> = { TWB_DATA_DIR: '/tmp/twb-e2e-x/data' }, code = 0) {
  const printEnvironment = `process.stdout.write(JSON.stringify(process.env)); process.exit(${code});`;
  return spawnSync(process.execPath, [LAUNCHER], {
    env: {
      ...SHELL,
      PATH: process.env.PATH,
      ...extra,
      TWB_E2E_BACKEND_COMMAND: JSON.stringify([process.execPath, '-e', printEnvironment]),
      TWB_E2E_BACKEND_SETTINGS: JSON.stringify(settings),
    },
    encoding: 'utf8',
  });
}

describe('backendEnvironment', () => {
  it('keeps the operating-system variables and the test settings, and nothing else', () => {
    const settings = { TWB_DATA_DIR: '/tmp/twb-e2e-x/data', TWB_CORS_ORIGINS: '["http://127.0.0.1:4183"]' };
    expect(backendEnvironment(SHELL, settings)).toEqual({
      PATH: '/usr/local/bin:/usr/bin:/bin',
      HOME: '/home/reviewer',
      LANG: 'C.UTF-8',
      ...settings,
    });
  });

  it('recognises the Windows spellings of system variables', () => {
    const windows = { Path: 'C:\\Windows', SystemRoot: 'C:\\Windows', USERPROFILE: 'C:\\Users\\r', ComSpec: 'cmd.exe', twb_auth__tokens: '["x"]' };
    expect(backendEnvironment(windows, {})).toEqual({
      Path: 'C:\\Windows',
      SystemRoot: 'C:\\Windows',
      USERPROFILE: 'C:\\Users\\r',
      ComSpec: 'cmd.exe',
    });
  });

  it('refuses settings that are not strings', () => {
    expect(() => backendEnvironment({}, { TWB_DATA_DIR: 3 })).toThrow(TypeError);
  });
});

describe('backend launcher', () => {
  it('starts the backend without any inherited TWB_* variable', () => {
    const result = launch();
    expect(result.status).toBe(0);
    const environment = JSON.parse(result.stdout);
    expect(Object.keys(environment).filter((name) => name.toUpperCase().startsWith('TWB_'))).toEqual(['TWB_DATA_DIR']);
    expect(environment.TWB_DATA_DIR).toBe('/tmp/twb-e2e-x/data');
    expect(environment.PATH).toBe(process.env.PATH);
    expect(environment.HOME).toBe('/home/reviewer');
    for (const name of ['PYTHONPATH', 'VIRTUAL_ENV', 'AWS_SECRET_ACCESS_KEY', 'TWB_E2E_BACKEND_COMMAND']) {
      expect(environment).not.toHaveProperty(name);
    }
  });

  it("exits with the backend's exit code", () => {
    expect(launch({}, {}, 3).status).toBe(3);
  });

  it('refuses a missing or malformed command', () => {
    const result = spawnSync(process.execPath, [LAUNCHER], {
      env: { PATH: process.env.PATH, TWB_E2E_BACKEND_COMMAND: '"uvicorn app.main:app"', TWB_E2E_BACKEND_SETTINGS: '{}' },
      encoding: 'utf8',
    });
    expect(result.status).toBe(2);
    expect(result.stderr).toContain('TWB_E2E_BACKEND_COMMAND must be a JSON array of strings');
  });
});

describe('outputDirFor', () => {
  it('gives each checkout its own folder in the temporary directory', () => {
    const first = outputDirFor({}, '/work/twb-a/frontend', '/tmp');
    expect(dirname(first)).toBe(join('/tmp'));
    expect(basename(first)).toMatch(/^twb-e2e-results-[0-9a-f]{10}$/);
    expect(outputDirFor({}, '/work/twb-a/frontend', '/tmp')).toBe(first);
    expect(outputDirFor({}, '/work/twb-b/frontend', '/tmp')).not.toBe(first);
  });

  it('uses TWB_E2E_OUTPUT_DIR when it is set', () => {
    expect(outputDirFor({ TWB_E2E_OUTPUT_DIR: '/ci/tmp/twb-e2e-results' }, '/work/twb-a/frontend', '/tmp')).toBe(
      '/ci/tmp/twb-e2e-results',
    );
  });
});
