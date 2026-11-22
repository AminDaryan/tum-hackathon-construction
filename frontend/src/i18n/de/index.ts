/**
 * German for the pages' own text, keyed by the English source text: English stays in the code
 * and is looked up here when German is on. One file per area of the app, merged into the `de`
 * table of messages.ts; the same English text has the same German everywhere (the catalogue test
 * checks it). Keep the `{placeholders}` of the English text, and no middle dots.
 */
import { app } from './app.ts';
import { clarifications } from './clarifications.ts';
import { panel } from './panel.ts';
import { projects } from './projects.ts';
import { report } from './report.ts';
import { review } from './review.ts';
import { shared } from './shared.ts';
import { sheet } from './sheet.ts';
import { workspace } from './workspace.ts';

export const AREAS = Object.freeze({ app, clarifications, panel, projects, report, review, shared, sheet, workspace });

export const DE: Readonly<Record<string, string>> = Object.freeze(Object.assign({}, ...Object.values(AREAS)));
