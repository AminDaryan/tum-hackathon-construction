import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { backendPython, billPath, dataDir } from './environment.ts';

/** Writes the bill the test uploads, with the backend's Python and openpyxl (make_bill.py). */
export default function globalSetup() {
  mkdirSync(dataDir, { recursive: true });
  const script = join(dirname(fileURLToPath(import.meta.url)), 'make_bill.py');
  execFileSync(backendPython().python, ['-I', script, billPath], { stdio: 'inherit' });
}
