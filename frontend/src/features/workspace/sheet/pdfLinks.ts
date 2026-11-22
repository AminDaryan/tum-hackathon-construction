import type { PdfSource } from './SheetPdf.tsx';

/** The PDF the sheet's "PDF" view shows for a file: an uploaded PDF shows itself; other files have none. */
export function pdfSourceFor(
  document: { document_id: string; original_filename: string; format: string } | null,
): PdfSource | null {
  return document?.format === 'pdf' ? { documentId: document.document_id, file: document.original_filename } : null;
}
