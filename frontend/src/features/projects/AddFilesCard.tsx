import { useState, type RefObject } from 'react';
import { ErrorState } from '../../components/ErrorState.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { t } from '../../i18n/messages.ts';
import { ACCEPTED_EXTENSIONS } from '../documents/uploadRules.ts';
import { FilesDropzone } from './FilesDropzone.tsx';
import { uploadSummary, uploadToProject } from './projectUpload.ts';

/**
 * The state of "Add files", kept by the project page so that an upload in progress or its
 * warnings survive the card moving in the page.
 */
export function useAddFiles(projectId: string, onChanged: () => void) {
  const [progress, setProgress] = useState('');
  const [failures, setFailures] = useState<string[]>([]);
  const action = useAsyncAction(async (signal, run: (signal: AbortSignal) => Promise<void>) => run(signal));

  const upload = async (files: File[]) => {
    setFailures([]);
    await action.execute(async (signal) => {
      const failed = await uploadToProject(projectId, files, { signal, onProgress: setProgress });
      setFailures(failed);
      setProgress(uploadSummary(files.length, failed));
    });
    onChanged();
  };
  return { progress, failures, upload, pending: action.pending, error: action.error };
}

interface AddFilesCardProps {
  files: ReturnType<typeof useAddFiles>;
  /** The project is being validated: the box is off and says so. */
  disabled?: boolean;
  /** The project is still loading: the box is off, with its usual text. */
  loading?: boolean;
  inputRef?: RefObject<HTMLInputElement | null>;
}

/**
 * "Add files" on the project page, a box filling the height it is given: drop one or several
 * files on it, or choose them. Every file is added as a bill of quantities. Uploading waits while the project is validated, because its files
 * cannot change then, and while the project loads, because whether one runs is not known yet.
 * `files` is the state from `useAddFiles`.
 */
export function AddFilesCard({ files, disabled, loading, inputRef }: AddFilesCardProps) {
  const { progress, failures, pending } = files;
  const busy = disabled || loading || pending;
  const upload = (chosen: File[]) => (busy ? undefined : files.upload(chosen));

  return (
    <section aria-labelledby="add-files-heading" aria-busy={pending || undefined} className="flex min-h-40 flex-1 flex-col gap-2">
      <h2 id="add-files-heading" className="sr-only">
        {t('Add files')}
      </h2>
      <FilesDropzone
        onFiles={upload}
        disabled={busy}
        inputRef={inputRef}
        accept={ACCEPTED_EXTENSIONS}
        label={disabled && !pending ? t('Files can be added again once the project’s validation has finished.') : t('Drop files here, or')}
        buttonLabel={t('Add files…')}
        hint={null}
        className="flex-1"
      />
      {progress && (
        <p role="status" className="text-callout text-ink-secondary">
          {progress}
        </p>
      )}
      {files.error && <ErrorState error={files.error} title={t('The files could not be added')} compact />}
      {failures.length > 0 && (
        <ul role="alert" className="flex flex-col gap-1 break-words text-callout text-danger">
          {failures.map((failure) => (
            <li key={failure}>{failure}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
