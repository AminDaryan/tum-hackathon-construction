import { Disclosure } from '../../../components/Disclosure.tsx';
import { KeyValueList } from '../../../components/KeyValueList.tsx';
import { Section } from '../../../components/Section.tsx';
import { StatusBadge } from '../../../components/StatusBadge.tsx';
import { Timestamp } from '../../../components/Timestamp.tsx';
import { t } from '../../../i18n/messages.ts';
import { formatBytes } from '../../../utils/format.ts';
import { DOCUMENT_FORMAT_LABELS, labelFor } from '../../../utils/vocabulary.ts';
import { DownloadExcelButton } from '../../exports/DownloadExcelButton.tsx';
import { extractionFacts } from './gaebFacts.ts';
import { ModelAttachment } from './ModelAttachment.tsx';
import type { DatasetSummary, DocumentSummary } from '../../../services/apiTypes.ts';

function versioned(id: unknown, version: unknown) {
  return `${id ?? ''} ${version ?? ''}`.trim() || null;
}

/** A section of the tab that is always open, between hairlines. */
const BLOCK = 'py-4 first:pt-0 last:pb-0';
/** A section that opens under its title: a row of its own between hairlines. */
const FOLD = 'py-2 last:pb-0';
/** What a section shows when open, in line with its title's text. */
const FOLD_BODY = 'pb-2 pl-5';

interface PropertiesTabProps {
  document: DocumentSummary;
  dataset: DatasetSummary;
  onModelChanged: () => void;
}

/**
 * Every specification of the open file, as one list of sections between hairlines on the panel's
 * own surface: the file and how well it was read, with the download of the table as Excel (the
 * newest revision, edits included); its design model (IFC); then sections that open under their
 * title for the technical details and the GAEB facts (for a GAEB bill).
 */
export function PropertiesTab({ document, dataset, onModelChanged }: PropertiesTabProps) {
  const { extraction } = dataset;
  const { gaeb, other } = extractionFacts(extraction.details);

  return (
    <div className="divide-y divide-hairline">
      <div className={BLOCK}>
        <Section title={t('File')} surface={false}>
          <KeyValueList
            layout="inline"
            items={[
              { label: t('Name'), value: <span className="break-all">{document.original_filename}</span> },
              { label: t('Format'), value: t(labelFor(DOCUMENT_FORMAT_LABELS, document.format)) },
              { label: t('Size'), value: Number.isFinite(document.size_bytes) ? formatBytes(document.size_bytes) : null },
              { label: t('Uploaded'), value: <Timestamp value={document.uploaded_at} /> },
              { label: t('Reading quality'), value: <StatusBadge kind="quality" status={extraction.quality} /> },
            ]}
          />
          <div className="mt-4">
            <DownloadExcelButton datasetId={dataset.dataset_id} label={t('Download table as Excel')} />
          </div>
        </Section>
      </div>

      <div className={BLOCK}>
        <ModelAttachment document={document} onChanged={onModelChanged} />
      </div>

      <div className={FOLD}>
        <Disclosure title={t('Technical details')} size="headline">
          <section aria-label={t('Technical details')} className={FOLD_BODY}>
            <KeyValueList
              layout="inline"
              items={[
                { label: 'SHA-256', value: document.sha256 ? <span className="break-all">{document.sha256}</span> : null, mono: true },
                { label: t('Profile'), value: versioned(dataset.profile_id, dataset.profile_version), mono: true },
                { label: t('Read by'), value: versioned(extraction.adapter_id, extraction.adapter_version), mono: true },
                ...other,
              ]}
            />
          </section>
        </Disclosure>
      </div>

      {gaeb && (
        <div className={FOLD}>
          <Disclosure title="GAEB" size="headline">
            <section aria-label="GAEB" className={FOLD_BODY}>
              <KeyValueList layout="inline" items={gaeb} />
            </section>
          </Disclosure>
        </div>
      )}
    </div>
  );
}
