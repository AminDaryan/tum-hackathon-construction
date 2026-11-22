import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';

const frontend = join(dirname(fileURLToPath(import.meta.url)), '..');
const forbidden = /[\u00B7\u2219\u22C5\u30FB]|\\u(?:00b7|2219|22c5|30fb)|&(?:middot|#183|#x0*b7);/i;

// App-authored copy only: never scan uploaded text, PDF/GAEB assets, dependencies or docs.
// Check middle-dot separators, not every Unicode dot.
// Genuine mathematical/unit notation in authored source needs a narrowly reviewed exception,
// not replacement with punctuation. There are currently no such occurrences in this scope.
test('app-authored UI contains no middle-dot separators', () => {
  const files = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', 'src', 'index.html'], {
    cwd: frontend,
    encoding: 'utf8',
  }).split('\0').filter((file) =>
    /\.(jsx?|tsx?|css|html|json)$/.test(file) && !/(^|\/)(test|__tests__|fixtures)\/|\.(test|spec)\.[^.]+$/.test(file),
  );
  expect(files).toContain('index.html');
  expect(files).toContain('src/app/App.tsx');
  expect(files).toContain('src/features/projects/ProjectsPage.tsx');

  const hits = [...new Set(files)].sort().flatMap((file) =>
    readFileSync(join(frontend, file), 'utf8').split('\n').flatMap((line, index) =>
      forbidden.test(line) ? [`${file}:${index + 1}: ${line.trim()}`] : [],
    ),
  );
  expect(hits, 'Use readable labels, spacing or layout instead of middle-dot separators.').toEqual([]);
});
