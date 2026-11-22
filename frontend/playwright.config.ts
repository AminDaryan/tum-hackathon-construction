/**
 * Browser end-to-end test: `npm run test:e2e` (Playwright, Chromium).
 *
 * Playwright starts the backend (uvicorn, with a temporary TWB_DATA_DIR) and the built web
 * interface (`vite build`, then `vite preview`, which proxies /api to that backend);
 * e2e/workbench.spec.ts walks through the main workflow and e2e/touch-targets.spec.ts measures
 * hit areas. The backend starts through e2e/backend-launcher.ts, which passes
 * it only the settings below plus PATH, HOME and the like: no TWB_* variable of your shell (an
 * access token, a database URL) reaches it. Optional environment variables of the test itself:
 *
 *   TWB_E2E_BACKEND_PORT   backend port (default 8133)
 *   TWB_E2E_PREVIEW_PORT   vite preview port (default 4183)
 *   TWB_E2E_BACKEND_DIR    directory holding the backend's `app` package (default ../backend)
 *   TWB_E2E_PYTHON         Python with the backend's dependencies (default: the backend's .venv,
 *                          with uvicorn from its bin directory; else python3 on PATH)
 *   TWB_E2E_CHROMIUM_PATH  Chromium to launch (default: Playwright's own; when it is not
 *                          installed, /opt/pw-browsers/chromium)
 *   TWB_E2E_DATA_DIR       backend data directory (default: inside a new temporary directory)
 *   TWB_E2E_TMP_DIR        temporary directory for the data and the bill (kept when given;
 *                          a directory the configuration creates is removed afterwards)
 *   TWB_E2E_OUTPUT_DIR     Playwright's output directory (default: twb-e2e-results-<short
 *                          hash of this frontend directory> in the system's temporary
 *                          directory, so two checkouts never share one)
 */
import { chromium, defineConfig, devices } from '@playwright/test';
import {
  backendDir,
  backendPort,
  backendPython,
  chromiumExecutable,
  dataDir,
  outputDir,
  previewOrigin,
  previewPort,
} from './e2e/environment.ts';

const executablePath = chromiumExecutable(chromium.executablePath());
const uvicorn = [
  ...backendPython().uvicorn,
  'app.main:create_app',
  '--factory',
  '--app-dir',
  backendDir,
  '--host',
  '127.0.0.1',
  '--port',
  String(backendPort),
];
/** Everything the backend is given (e2e/backend-launcher.ts adds PATH, HOME and the like). */
const backendSettings = {
  TWB_DATA_DIR: dataDir,
  // The browser's Origin is the preview server; the backend accepts state-changing requests
  // only from allowed origins.
  TWB_CORS_ORIGINS: JSON.stringify([previewOrigin, `http://localhost:${previewPort}`]),
};

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  outputDir,
  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: previewOrigin,
    acceptDownloads: true,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 }, launchOptions: { executablePath } },
    },
  ],
  webServer: [
    {
      command: 'node e2e/backend-launcher.ts',
      url: `http://127.0.0.1:${backendPort}/api/v1/health`,
      env: {
        TWB_E2E_BACKEND_COMMAND: JSON.stringify(uvicorn),
        TWB_E2E_BACKEND_SETTINGS: JSON.stringify(backendSettings),
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run build && npx vite preview --host 127.0.0.1 --port ${previewPort} --strictPort`,
      url: previewOrigin,
      env: { TWB_API_PROXY_TARGET: `http://127.0.0.1:${backendPort}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
