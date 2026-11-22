import { Upload } from 'lucide-react';
import { useRef, useState, type RefObject } from 'react';
import { Button } from '../../components/Button.tsx';
import { t } from '../../i18n/messages.ts';
import { cx } from '../../utils/classNames.ts';
import { ACCEPTED_EXTENSIONS, acceptedFormatsText } from '../documents/uploadRules.ts';

interface FilesDropzoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  accept?: readonly string[];
  inputRef?: RefObject<HTMLInputElement | null>;
  label?: string;
  /** The line under the button; `null` leaves it out. */
  hint?: string | null;
  className?: string;
  /** The button's text. */
  buttonLabel?: string;
}

/**
 * A box to drop one or several files on. A click anywhere in the box opens the file chooser;
 * "Choose files…" stays as the keyboard path. `inputRef` lets another control open the same
 * file chooser.
 */
export function FilesDropzone({
  onFiles,
  disabled = false,
  accept = ACCEPTED_EXTENSIONS,
  inputRef,
  label = t('Drop files here, or'),
  hint = t('Supported: {formats}. One file or several at once.', { formats: acceptedFormatsText() }),
  className,
  buttonLabel = t('Choose files…'),
}: FilesDropzoneProps) {
  const ownRef = useRef<HTMLInputElement>(null);
  const input = inputRef ?? ownRef;
  const dragDepth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const pick = (list: FileList | null | undefined) => {
    const files = Array.from(list ?? []);
    if (files.length) onFiles(files);
  };
  return (
    // The box is a larger pointer target for the button inside it, which keyboard users reach.
    <div
      onClick={(event) => {
        if (disabled || (event.target as Element).closest('button, input')) return;
        input.current?.click();
      }}
      onDragEnter={(event) => {
        event.preventDefault();
        if (disabled || !event.dataTransfer?.types?.includes('Files')) return;
        dragDepth.current += 1;
        setDragging(true);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = disabled ? 'none' : 'copy';
      }}
      onDragLeave={() => {
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (!dragDepth.current) setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        dragDepth.current = 0;
        setDragging(false);
        if (!disabled) pick(event.dataTransfer?.files);
      }}
      className={cx(
        'flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center transition-colors',
        dragging ? 'border-accent bg-accent-subtle' : 'border-hairline-strong bg-surface-muted',
        disabled ? 'opacity-60' : 'cursor-pointer hover:border-accent',
        className,
      )}
    >
      <span aria-hidden="true" className="inline-flex size-10 items-center justify-center rounded-full bg-accent-subtle text-accent-strong">
        <Upload className="size-5" strokeWidth={1.75} />
      </span>
      <p className="text-body text-ink">{dragging ? t('Drop the files to add them') : label}</p>
      <Button icon={Upload} isDisabled={disabled} onPress={() => input.current?.click()}>
        {buttonLabel}
      </Button>
      <input
        ref={input}
        type="file"
        multiple
        accept={accept.join(',')}
        aria-label={t('Choose files to upload')}
        tabIndex={-1}
        className="sr-only"
        disabled={disabled}
        onChange={(event) => {
          pick(event.target.files);
          event.target.value = '';
        }}
      />
      {hint && <p className="max-w-md text-caption text-ink-secondary">{hint}</p>}
    </div>
  );
}
