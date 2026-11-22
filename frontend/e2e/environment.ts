/**
 * Settings of the browser end-to-end test, shared by playwright.config.ts and the global setup.
 * Every value can be overridden through the environment (see playwright.config.ts).
 */
import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { outputDirFor } from './isolation.ts';

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** Chromium installed for the machine-wide Playwright (used when the pinned one has none). */
export const PREINSTALLED_CHROMIUM = '/opt/pw-browsers/chromium';

export const backendPort = Number(process.env.TWB_E2E_BACKEND_PORT || 8133);
export const previewPort = Number(process.env.TWB_E2E_PREVIEW_PORT || 4183);
export const backendDir = resolve(frontendDir, process.env.TWB_E2E_BACKEND_DIR || '../backend');
export const previewOrigin = `http://127.0.0.1:${previewPort}`;

// The configuration is evaluated in the main process and again in every worker; workers inherit
// the main process's environment, so the temporary directory is created only once.
if (!process.env.TWB_E2E_TMP_DIR) {
  process.env.TWB_E2E_TMP_DIR = mkdtempSync(join(tmpdir(), 'twb-e2e-'));
  process.env.TWB_E2E_TMP_CREATED = '1';
}

/** Temporary directory of this test run: backend data and the generated bill. */
export const tmpDir = process.env.TWB_E2E_TMP_DIR;
/**
 * Playwright's output (failure context, last-run state). It is written after the global
 * teardown, so it lives in one folder per checkout that Playwright empties at the start of each
 * run: `TWB_E2E_OUTPUT_DIR`, else twb-e2e-results-<short hash of this frontend directory> in the
 * system's temporary directory.
 */
export const outputDir = outputDirFor(process.env, frontendDir);
export const dataDir = process.env.TWB_E2E_DATA_DIR || join(tmpDir, 'data');
export const billPath = join(tmpDir, 'e2e-bill.xlsx');

const venvBin = join(backendDir, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin');
const executable = (name: string) => join(venvBin, process.platform === 'win32' ? `${name}.exe` : name);

/**
 * The Python that has the backend's dependencies, and the command that starts uvicorn with it:
 * `TWB_E2E_PYTHON`, else the backend's virtual environment (uvicorn from its bin directory),
 * else Python on PATH.
 */
export function backendPython(): { python: string, uvicorn: string[] } {
  if (process.env.TWB_E2E_PYTHON) {
    return { python: process.env.TWB_E2E_PYTHON, uvicorn: [process.env.TWB_E2E_PYTHON, '-m', 'uvicorn'] };
  }
  if (existsSync(executable('uvicorn'))) {
    return { python: executable('python'), uvicorn: [executable('uvicorn')] };
  }
  const python = process.platform === 'win32' ? 'python' : 'python3';
  return { python, uvicorn: [python, '-m', 'uvicorn'] };
}

/**
 * The Chromium to launch: `TWB_E2E_CHROMIUM_PATH`, else Playwright's own browser (undefined),
 * else the preinstalled one.
 *
 * @param ownExecutable where the pinned Playwright expects its Chromium
 */
export function chromiumExecutable(ownExecutable: string): string | undefined {
  if (process.env.TWB_E2E_CHROMIUM_PATH) return process.env.TWB_E2E_CHROMIUM_PATH;
  if (existsSync(ownExecutable)) return undefined;
  return existsSync(PREINSTALLED_CHROMIUM) ? PREINSTALLED_CHROMIUM : undefined;
}
