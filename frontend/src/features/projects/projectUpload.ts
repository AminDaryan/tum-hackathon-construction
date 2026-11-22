import { t } from '../../i18n/messages.ts';
import { uploadDocument } from '../../services/documentsService.ts';
import { addProjectFile } from '../../services/projectsService.ts';
import { pluralize } from '../../utils/format.ts';
import { isAcceptedFile, rejectionMessage } from '../documents/uploadRules.ts';

/**
 * Adds files to a project, one bounded request per file (the server's streaming upload limits
 * stay in force), and returns one line per file that was not added. A rejected file does not stop
 * its neighbours. Every file is a bill of quantities, read with the BoQ profile.
 */
export async function uploadToProject(
  projectId: string,
  files: File[],
  { signal, onProgress }: { signal?: AbortSignal; onProgress?: (text: string) => void } = {},
): Promise<string[]> {
  const failures: string[] = [];
  for (const [index, file] of files.entries()) {
    onProgress?.(t('Reading {file} ({index} of {total})', { file: file.name, index: index + 1, total: files.length }));
    try {
      if (!isAcceptedFile(file)) throw new Error(rejectionMessage(file));
      const detail = await uploadDocument(file, { profileId: 'boq', signal });
      await addProjectFile(projectId, detail.document.document_id, 'bill', signal);
      if (!detail.dataset) failures.push(t('{file}: stored, but its tables could not be read.', { file: file.name }));
    } catch (error) {
      if (signal?.aborted) throw error;
      failures.push(`${file.name}: ${(error as Error).message}`);
    }
  }
  return failures;
}

/** "3 files added." or "Added: 2 files. Could not be added: 1 file." */
export function uploadSummary(count: number, failures: string[]): string {
  if (failures.length) {
    return t('Added: {added}. Could not be added: {failed}.', {
      added: pluralize(count - failures.length, 'file'),
      failed: pluralize(failures.length, 'file'),
    });
  }
  return t('{files} added.', { files: pluralize(count, 'file') });
}
