/** Conservative, literal whole-token matching. No stemming, synonyms or inferred materials.
 * Shared with material quantity views: callers supply the evidence text and review candidates.
 */
export function matchesMaterial(text: string | null | undefined, query: string | null | undefined): boolean {
  const tokens = (value: string | null | undefined) => String(value ?? '').normalize('NFKC').toLocaleLowerCase('de-DE').match(/[\p{L}\p{N}]+/gu) ?? [];
  const haystack = tokens(text);
  const needle = tokens(query);
  return needle.length > 0 && haystack.some((_, start) =>
    needle.every((token, index) => haystack[start + index] === token));
}
