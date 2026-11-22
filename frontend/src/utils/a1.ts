/**
 * Spreadsheet A1 helpers. Mirrors backend/app/core/a1.py so the UI labels columns the same way.
 */

/**
 * Converts a 1-based column number to letters: 1 -> A, 27 -> AA.
 *
 * @returns the column letters, or an empty string for invalid input
 */
export function columnLetter(columnNumber: number): string {
  if (!Number.isInteger(columnNumber) || columnNumber < 1) {
    return '';
  }
  let remaining = columnNumber;
  let letters = '';
  while (remaining > 0) {
    const remainder = (remaining - 1) % 26;
    letters = String.fromCharCode(65 + remainder) + letters;
    remaining = Math.floor((remaining - 1) / 26);
  }
  return letters;
}

/** A1 reference such as `C12` for 1-based row and column numbers. */
export function a1Reference(
  rowNumber: number | null | undefined,
  columnNumber: number | null | undefined,
): string | null {
  const letters = columnLetter(columnNumber ?? 0);
  if (!letters || !rowNumber || !Number.isInteger(rowNumber) || rowNumber < 1) {
    return null;
  }
  return `${letters}${rowNumber}`;
}
