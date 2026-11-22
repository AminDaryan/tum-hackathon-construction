import { rmSync } from 'node:fs';
import { tmpDir } from './environment.ts';

/** Removes the temporary directory of this run when the configuration created it. */
export default function globalTeardown() {
  if (process.env.TWB_E2E_TMP_CREATED === '1') {
    rmSync(tmpDir, { recursive: true, force: true, maxRetries: 3 });
  }
}
