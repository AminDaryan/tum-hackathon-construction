import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test } from 'vitest';
import { AREAS } from './de/index.ts';
import { MESSAGES } from './messages.ts';

const { en: EN, de: DE } = MESSAGES;
/** A dotted key (`nav.projects`) has its English in messages.ts; any other key is its English. */
const english = (key: string) => EN[key] ?? key;

const frontend = join(dirname(fileURLToPath(import.meta.url)), '../..');
const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();

/** Every literal passed to t(), tRich() or msg() in the app's source, with where it is. */
function sourceMessages() {
  const files = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', 'src'], {
    cwd: frontend,
    encoding: 'utf8',
  }).split('\0').filter((file) => /\.[jt]sx?$/.test(file) && !/(^|\/)test\/|\.test\.[^.]+$/.test(file));
  const call = /\b(?:t|tRich|msg)\(\s*(?:'((?:\\.|[^'\\])*)'|"((?:\\.|[^"\\])*)"|`((?:\\.|[^`\\])*)`)/g;
  return files.flatMap((file) =>
    [...readFileSync(join(frontend, file), 'utf8').matchAll(call)].map((match) => ({
      file,
      raw: match[1] ?? match[2] ?? match[3],
      template: match[3] !== undefined,
    })),
  );
}

const unescape = (raw: string) => raw.replace(/\\(.)/g, '$1');

test('every message in the source has a German translation', () => {
  const messages = sourceMessages();
  expect(messages.length).toBeGreaterThan(10);
  // Built dotted keys (`role.${role}`) are fine; English text uses {placeholders} instead.
  const interpolated = messages.filter((m) => m.template && m.raw.includes('${') && !/^[\w.${}]+$/.test(m.raw));
  expect(interpolated.map((m) => `${m.file}: ${m.raw}`), 'Use {placeholders}, not ${}, in messages').toEqual([]);
  const missing = [...new Set(messages.filter((m) => !m.raw.includes('${')).map((m) => unescape(m.raw)).filter((text) => !(text in DE)))];
  expect(missing, 'Add these to a German catalogue in src/i18n/de').toEqual([]);
});

test('German keeps the placeholders and one translation per English text', () => {
  expect(Object.keys(EN).filter((key) => !(key in DE)), 'Dotted keys need German in messages.ts').toEqual([]);
  const broken = Object.entries(DE).filter(([en, de]) => placeholders(english(en)).join() !== placeholders(de).join());
  expect(broken).toEqual([]);
  const seen = new Map();
  const conflicts = [];
  for (const [area, entries] of Object.entries(AREAS)) {
    for (const [en, de] of Object.entries(entries)) {
      if (seen.has(en) && seen.get(en).de !== de) conflicts.push(`"${en}": ${seen.get(en).area} "${seen.get(en).de}" vs ${area} "${de}"`);
      seen.set(en, { area, de });
    }
  }
  expect(conflicts).toEqual([]);
});
