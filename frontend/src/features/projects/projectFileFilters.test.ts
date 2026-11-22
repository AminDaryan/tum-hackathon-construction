import { describe, expect, it } from 'vitest';
import { documentSummary } from '../../test/fixtures.ts';
import { filterFiles, NO_FILE_FILTERS, type FileType } from './projectFileFilters.ts';
import type { DocumentSummary } from '../../services/apiTypes.ts';

function file(id: string, name: string, uploadedAt: string, overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return { ...documentSummary, document_id: id, original_filename: name, uploaded_at: uploadedAt, last_run: null, ...overrides };
}

const bill = file('doc_1', 'Rohbau.x83', '2026-11-20T10:00:00Z');
const failed = file('doc_2', 'Ausbau.x83', '2026-11-21T10:00:00Z', { processing_status: 'failed' });
const drawing = file('doc_3', 'Grundriss.pdf', '2026-11-21T10:00:00Z', { processing_status: 'failed' });
const types: Record<string, FileType> = { doc_1: 'bill', doc_2: 'bill', doc_3: 'support' };
const typeOf = (doc: DocumentSummary) => types[doc.document_id];
const counts = { doc_1: { findings: 3, to_review: 2, high_priority: 1, by_severity: { high: 1, low: 2 } } };
const names = (docs: DocumentSummary[]) => docs.map((doc) => doc.original_filename);

describe('filterFiles', () => {
  it('lists the newest upload first, and files uploaded at the same time by name', () => {
    expect(names(filterFiles([bill, drawing, failed], NO_FILE_FILTERS, typeOf, counts))).toEqual(['Ausbau.x83', 'Grundriss.pdf', 'Rohbau.x83']);
  });

  it('keeps the files of a type, with findings, or needing attention; a supporting document never needs attention', () => {
    const files = [bill, failed, drawing];
    expect(names(filterFiles(files, { ...NO_FILE_FILTERS, type: 'support' }, typeOf, counts))).toEqual(['Grundriss.pdf']);
    expect(names(filterFiles(files, { ...NO_FILE_FILTERS, state: 'high' }, typeOf, counts))).toEqual(['Rohbau.x83']);
    expect(names(filterFiles(files, { ...NO_FILE_FILTERS, state: 'attention' }, typeOf, counts))).toEqual(['Ausbau.x83']);
  });

  it('finds a file by any word of its name, ignoring case and accents', () => {
    const umlaut = file('doc_4', 'Gebäude Süd.d86', '2026-11-19T10:00:00Z');
    expect(names(filterFiles([bill, umlaut], { ...NO_FILE_FILTERS, search: 'sud geba' }, () => 'bill', {}))).toEqual(['Gebäude Süd.d86']);
  });
});
