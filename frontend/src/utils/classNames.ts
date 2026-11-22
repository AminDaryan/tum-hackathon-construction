/** Joins CSS class names, skipping falsy entries so conditional classes stay readable. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}
