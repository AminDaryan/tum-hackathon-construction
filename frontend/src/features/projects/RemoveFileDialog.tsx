import { Trash2 } from 'lucide-react';
import { Button } from '../../components/Button.tsx';
import { Dialog } from '../../components/Dialog.tsx';
import { t } from '../../i18n/messages.ts';
import type { DocumentSummary } from '../../services/apiTypes.ts';

interface RemoveFileDialogProps {
  /** the file to remove; null keeps the dialog closed */
  file: Pick<DocumentSummary, 'document_id' | 'original_filename'> | null;
  onCancel: () => void;
  onConfirm: (documentId: string) => void;
}

/**
 * Asks before a file leaves a project, and says what that does: the uploaded file is kept (and
 * stays in other projects), and the project needs validating again; its decisions so far are kept.
 */
export function RemoveFileDialog({ file, onCancel, onConfirm }: RemoveFileDialogProps) {
  return (
    <Dialog
      open={file !== null}
      onOpenChange={(open) => !open && onCancel()}
      role="alertdialog"
      title={t('Remove {file} from this project?', { file: file?.original_filename ?? '' })}
      size="sm"
    >
      <div className="flex flex-col gap-4">
        <p className="text-callout text-ink">
          {t('The uploaded file is kept, and stays in any other project that uses it. Validate the project again afterwards; the decisions made so far are kept.')}
        </p>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onPress={onCancel}>
            {t('Cancel')}
          </Button>
          <Button variant="danger" icon={Trash2} onPress={() => file && onConfirm(file.document_id)}>
            {t('Remove from project')}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
