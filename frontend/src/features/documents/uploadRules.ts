/**
 * Client-side upload rules. The backend stays authoritative (it sniffs content and enforces size
 * limits); these rules only give immediate feedback and configure the file picker.
 */
import { intlLocale, t } from '../../i18n/messages.ts';

// The accepted formats, each with its extensions. GAEB bills by exchange phase: .x81 (bill
// exchange), .x83 (call for bids), .x84 (bid), .x86 (contract award) in DA XML 3.1, 3.2 and 3.3,
// and the same phases as GAEB 90 (.d81 ... .d86). .pdf: a printed bill of quantities, read from
// the PDF's text layer. .docx: a Word document; its tables, or a bill written as a list of item
// paragraphs.
const FORMATS: readonly { name: string; extensions: readonly string[] }[] = [
  { name: 'XLSX', extensions: ['.xlsx'] },
  { name: 'CSV', extensions: ['.csv'] },
  { name: 'TSV', extensions: ['.tsv'] },
  { name: 'TXT', extensions: ['.txt'] },
  { name: 'PDF', extensions: ['.pdf'] },
  { name: 'Word', extensions: ['.docx'] },
  { name: 'GAEB', extensions: ['.x81', '.x83', '.x84', '.x86', '.d81', '.d83', '.d84', '.d86'] },
];

export const ACCEPTED_EXTENSIONS = Object.freeze(FORMATS.flatMap((format) => format.extensions));

/**
 * The accepted formats as one list in the UI language, built from the same list the checks use:
 * "XLSX, CSV, …, Word (.docx) and GAEB (.x81, …)".
 */
export function acceptedFormatsText(): string {
  const names = FORMATS.map(({ name, extensions }) =>
    extensions.length === 1 && extensions[0] === `.${name.toLowerCase()}` ? name : `${name} (${extensions.join(', ')})`,
  );
  return new Intl.ListFormat(intlLocale(), { type: 'conjunction' }).format(names);
}

/**
 * Lower-case extension including the dot, e.g. ".xlsx"; empty when the name has none.
 */
function fileExtension(name: string): string {
  const index = name.lastIndexOf('.');
  return index > 0 ? name.slice(index).toLowerCase() : '';
}

/**
 * @returns whether the file has an accepted extension
 */
export function isAcceptedFile(file: Pick<File, 'name'>): boolean {
  return ACCEPTED_EXTENSIONS.includes(fileExtension(file.name));
}

/**
 * Why a file is not accepted, in the words a user acts on.
 *
 * @param file a file that {@link isAcceptedFile} refused
 */
export function rejectionMessage(file: Pick<File, 'name'>): string {
  if (fileExtension(file.name) === '.doc') {
    return t('“{name}” is a legacy Word file (.doc). Save it as .docx (Word: File > Save As > Word Document) or as PDF, and upload that.', {
      name: file.name,
    });
  }
  return t('“{name}” is not a supported file type. Supported: {formats}.', { name: file.name, formats: acceptedFormatsText() });
}
