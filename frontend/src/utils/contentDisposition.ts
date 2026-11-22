/**
 * Extracts the download filename from a Content-Disposition header (RFC 6266), preferring the
 * RFC 5987 `filename*` form. Path components are stripped so a header can never point outside
 * the browser's download folder.
 */
export function filenameFromContentDisposition(header: string | null | undefined): string | null {
  if (!header) {
    return null;
  }
  const extended = /filename\*\s*=\s*([^']*)'[^']*'([^;]+)/i.exec(header);
  if (extended) {
    try {
      return baseName(decodeURIComponent(extended[2].trim().replace(/^"|"$/g, '')));
    } catch {
      // Malformed percent-encoding: fall back to the plain filename parameter.
    }
  }
  const quoted = /filename\s*=\s*"((?:\\.|[^"\\])*)"/i.exec(header);
  if (quoted) {
    return baseName(quoted[1].replace(/\\(.)/g, '$1'));
  }
  const bare = /filename\s*=\s*([^;]+)/i.exec(header);
  return bare ? baseName(bare[1]) : null;
}

function baseName(name: string): string | null {
  const base = (name.split(/[\\/]/).pop() ?? '').trim();
  return base === '' ? null : base;
}
