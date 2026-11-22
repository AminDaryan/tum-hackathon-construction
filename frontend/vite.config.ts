import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * The FastAPI backend serves the REST API under /api/v1 on port 8000 during development.
 * `TWB_API_PROXY_TARGET` points the dev server and `vite preview` at another backend (the
 * browser end-to-end test starts its own on a separate port).
 */
const backendProxy = {
  '/api': { target: process.env.TWB_API_PROXY_TARGET || 'http://127.0.0.1:8000' },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: backendProxy },
  preview: { port: 4173, proxy: backendProxy },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Unit and component tests, and the unit tests of the browser test's helpers
    // (e2e/*.test.ts). The browser tests themselves (e2e/*.spec.ts, npm run test:e2e) run under
    // Playwright.
    include: ['src/**/*.test.{ts,tsx}', 'e2e/**/*.test.ts'],
    exclude: ['e2e/**/*.spec.ts', 'node_modules/**', 'dist/**'],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
