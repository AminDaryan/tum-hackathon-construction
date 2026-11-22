import { Box, Trash2, Upload } from 'lucide-react';
import { useRef } from 'react';
import { Button } from '../../../components/Button.tsx';
import { ErrorState } from '../../../components/ErrorState.tsx';
import { KeyValueList } from '../../../components/KeyValueList.tsx';
import { Section } from '../../../components/Section.tsx';
import { useAsyncAction } from '../../../hooks/useAsyncAction.ts';
import { t } from '../../../i18n/messages.ts';
import { attachModel, detachModel } from '../../../services/documentsService.ts';
import { formatCount } from '../../../utils/format.ts';
import type { DocumentSummary } from '../../../services/apiTypes.ts';

interface ModelAttachmentProps {
  document: Pick<DocumentSummary, 'document_id' | 'model'>;
  onChanged: () => void;
}

/**
 * Attach, replace or remove the design model (IFC) of a bill, with the model's facts under the
 * title, on the surface it is placed on. `onChanged` runs after the document changed, so the
 * workspace reloads it.
 */
export function ModelAttachment({ document, onChanged }: ModelAttachmentProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const attach = useAsyncAction((signal, file: File) => attachModel(document.document_id, file, { signal }));
  const detach = useAsyncAction((signal) => detachModel(document.document_id, { signal }));
  const model = document.model ?? null;
  const pending = attach.pending || detach.pending;
  const error = attach.error ?? detach.error;

  async function choose(files: FileList | null) {
    const file = files?.[0];
    if (!file) {
      return;
    }
    detach.reset();
    if (await attach.execute(file)) {
      onChanged();
    }
  }

  async function remove() {
    attach.reset();
    if (await detach.execute()) {
      onChanged();
    }
  }

  const actions = (
    <>
      <Button icon={Upload} loading={attach.pending} isDisabled={pending} onPress={() => inputRef.current?.click()}>
        {model ? t('Replace model…') : t('Attach IFC model…')}
      </Button>
      {model && (
        <Button icon={Trash2} variant="ghost" loading={detach.pending} isDisabled={pending} onPress={remove}>
          {t('Remove')}
        </Button>
      )}
      <input
        ref={inputRef}
        type="file"
        accept=".ifc"
        aria-label={t('Choose an IFC model to attach')}
        tabIndex={-1}
        className="sr-only"
        disabled={pending}
        onChange={(event) => {
          choose(event.target.files);
          event.target.value = '';
        }}
      />
    </>
  );

  return (
    <Section title={t('Design model (IFC)')} actions={actions} surface={false}>
      {error && <ErrorState error={error} title={t('The model could not be changed')} compact />}
      {model ? (
        <KeyValueList
          layout="inline"
          items={[
            { label: t('File'), value: model.filename },
            { label: t('Project'), value: model.project },
            { label: t('Schema'), value: model.schema_name, mono: true },
            { label: t('Elements'), value: formatCount(model.elements) },
            { label: t('Linked item numbers'), value: formatCount(model.linked_positions) },
            { label: t('Elements without an item number'), value: formatCount(model.unlinked_elements) },
          ]}
        />
      ) : (
        <p className="flex items-center gap-2 text-callout text-ink-secondary">
          <Box aria-hidden="true" className="size-4 text-ink-tertiary" strokeWidth={1.5} />
          {t('No model attached')}
        </p>
      )}
      {model && (
        <p className="mt-3 text-caption text-ink-tertiary">{t('The bill is compared with this model by itself.')}</p>
      )}
    </Section>
  );
}
