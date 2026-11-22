import { describe, expect, it } from 'vitest';
import { pdfSourceFor } from './pdfLinks.ts';

const doc = (name: string, format: string) => ({ document_id: 'doc_1', original_filename: name, format });

describe('pdfSourceFor', () => {
  it('shows an uploaded PDF itself', () => {
    expect(pdfSourceFor(doc('Leistungsverzeichnis.pdf', 'pdf'))).toEqual({ documentId: 'doc_1', file: 'Leistungsverzeichnis.pdf' });
  });

  it('has no PDF for any other file', () => {
    expect(pdfSourceFor(doc('tender.xlsx', 'xlsx'))).toBeNull();
    expect(pdfSourceFor(doc('Ausschreibung.x83', 'gaeb'))).toBeNull();
    expect(pdfSourceFor(null)).toBeNull();
  });
});
