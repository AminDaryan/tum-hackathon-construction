/**
 * What the sheet says about a cell's content: its text, how the app read it, and the short
 * form of a finding's explanation for the cell note.
 */
import { t } from '../../../i18n/messages.ts';
import { VALUE_MARKER_LABELS } from '../../../utils/vocabulary.ts';

/**
 * The cell's text as it stands in the file (`raw_value`); an empty or missing cell is "".
 */
export function rawText(cell: { raw_value?: string | null } | null | undefined): string {
  return cell?.raw_value ?? '';
}

/**
 * Whether the cell holds a number (right-aligned in the sheet).
 */
export function isNumberCell(cell: { data_type?: string } | null | undefined) {
  return cell?.data_type === 'number';
}

/**
 * How the app read the cell, when that adds something to its text: the parse note, the
 * meaning of a value marker, or that a number column's text was not read as a number.
 */
export function readingNote(
  cell: {
    data_type?: string;
    parse_status?: string;
    parse_note?: string | null;
    marker?: string | null;
  } | null | undefined,
  column: { inferred_type?: string },
): string | null {
  if (!cell) {
    return null;
  }
  if (cell.parse_note) {
    return cell.parse_note;
  }
  if (cell.parse_status === 'marker' && cell.marker && VALUE_MARKER_LABELS[cell.marker]) {
    return t(VALUE_MARKER_LABELS[cell.marker]);
  }
  const filled = cell.data_type && cell.data_type !== 'empty';
  if (column.inferred_type === 'number' && filled && cell.data_type !== 'number') {
    return t('Not read as a number');
  }
  return null;
}

/**
 * The first sentence of a text (up to and including its full stop, question or exclamation
 * mark followed by a space or the end), or the whole text when it has no sentence end.
 */
export function firstSentence(text: string | null | undefined): string {
  const value = (text ?? '').trim();
  const match = /^[\s\S]*?[.!?](?=\s|$)/.exec(value);
  return match ? match[0] : value;
}
