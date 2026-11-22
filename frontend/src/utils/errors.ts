/**
 * Error helpers shared by services, hooks and the ErrorState component.
 */
import { msg, t } from '../i18n/messages.ts';

/** True for cancellations raised by an AbortSignal (fetch, AbortController). */
export function isAbortError(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { name?: unknown }).name === 'AbortError';
}

/** What the reviewer can do next, per backend error code (docs/api/rest-api.md, "Errors"). */
const ERROR_HINTS: Readonly<Record<string, string>> = Object.freeze({
  file_too_large: msg('The file is larger than the upload limit. Split it, or raise the limit in the server settings.'),
  unsupported_format: msg('Upload an XLSX, CSV, TSV, TXT or GAEB (.x81, .x83, .x84) file whose content matches its extension.'),
  file_rejected:
    msg('The file failed a safety check. Export it again from the program that created it (a spreadsheet: save it again as XLSX or CSV) and upload that copy.'),
  unauthorized: msg('Sign in again with a valid access token.'),
  conflict: msg('It was changed in the meantime (for example in another tab). Reload it, check it and try again.'),
  invalid_review_transition:
    msg("This decision is not allowed from the issue's current status, which may have changed in the meantime. Reload the issue and check its status."),
});

/** One entry of `details.errors`: a plan problem (`step`, `message`) or a request problem (`loc`, `msg`). */
interface ErrorEntry {
  message?: string;
  msg?: string;
  code?: string;
  step?: number;
  loc?: unknown[];
}

function errorLine(entry: unknown): string {
  if (!entry || typeof entry !== 'object') return String(entry);
  const { message, msg: text, code, step, loc } = entry as ErrorEntry;
  const what = message ?? text ?? code ?? t('Invalid value.');
  if (typeof step === 'number' && Number.isInteger(step)) return t('Step {number}: {problem}', { number: step + 1, problem: what });
  if (Array.isArray(loc)) return `${loc.filter((part) => part !== 'body').join(' › ')}: ${what}`;
  return what;
}

/**
 * Normalizes any thrown value into what the UI shows: a message, what to do next, the problems
 * listed in `details.errors`, and the error code and request id from the backend error envelope
 * when they exist.
 */
interface DescribedError {
  message: string;
  hint: string | null;
  problems: string[];
  code: string | null;
  requestId: string | null;
  status: number | null;
}

export function describeError(error: unknown): DescribedError {
  if (error && typeof error === 'object') {
    const fields = error as { message?: unknown; code?: unknown; details?: { errors?: unknown }; requestId?: unknown; status?: unknown };
    const message =
      typeof fields.message === 'string' && fields.message.trim() !== ''
        ? fields.message
        : t('An unexpected error occurred.');
    const code = typeof fields.code === 'string' ? fields.code : null;
    const errors = fields.details?.errors;
    const problems = Array.isArray(errors) ? errors.map(errorLine) : [];
    return {
      message,
      hint: code && ERROR_HINTS[code] ? t(ERROR_HINTS[code]) : null,
      problems,
      code,
      requestId: typeof fields.requestId === 'string' ? fields.requestId : null,
      status: typeof fields.status === 'number' ? fields.status : null,
    };
  }
  return { message: t('An unexpected error occurred.'), hint: null, problems: [], code: null, requestId: null, status: null };
}
