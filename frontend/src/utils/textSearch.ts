/**
 * Whether any of `fields` contains every word of `query`, ignoring case and accents: "anna
 * müller" finds "Müller, Anna", "muller" finds "Müller". An empty query matches everything.
 */
export function matchesSearch(query: string, fields: readonly (string | null | undefined)[]): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const text = fields.map((field) => fold(field ?? '')).join('\n');
  return words.every((word) => text.includes(word));
}

function fold(text: string): string {
  return text.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLocaleLowerCase();
}
