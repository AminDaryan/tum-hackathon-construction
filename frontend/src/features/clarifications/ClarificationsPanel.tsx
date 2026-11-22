import { RotateCw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Badge } from '../../components/Badge.tsx';
import { Button } from '../../components/Button.tsx';
import type { DataTableColumn } from '../../components/DataTable.tsx';
import { Dialog } from '../../components/Dialog.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { TextField } from '../../components/Field.tsx';
import { Select } from '../../components/Select.tsx';
import { TableCard, TWO_LINE_ROW_REM } from '../../components/TableCard.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useDebouncedValue } from '../../hooks/useDebouncedValue.ts';
import { t } from '../../i18n/messages.ts';
import { createClarification, saveClarification, type Clarification, type ClarificationItem as Item } from '../../services/clarificationsService.ts';
import { updateProject } from '../../services/projectsService.ts';
import { ClarificationFilterBar } from './ClarificationFilterBar.tsx';
import { clarificationQuery, hasClarificationFilters, NO_CLARIFICATION_FILTERS, type ClarificationFilters } from './clarificationFilters.ts';
import { dueNote, formatDay, formatSent, kindOf, KINDS, PHASES, STATUSES } from './clarificationModel.ts';
import { clarificationKey, useClarificationPage, withSaved } from './useClarificationPage.ts';
import { ClarificationStatusSelect } from './ClarificationStatusSelect.tsx';

/** The most rows a page asks the server for; fewer when fewer fit the window. */
const PAGE_SIZE = 10;
/** How long the search waits after the last key before it asks the server. */
const SEARCH_DELAY_MS = 300;

interface CutoffFieldProps {
  projectId: string;
  cutoff?: string | null;
  disabled: boolean;
  onSaved: () => void;
}

/** The day of the bid decision, saved when the field is left or Enter is pressed. */
function CutoffField({ projectId, cutoff, disabled, onSaved }: CutoffFieldProps) {
  const [draft, setDraft] = useState(cutoff ?? '');
  const action = useAsyncAction((signal, day: string) => updateProject(projectId, { decision_cutoff: day || null }, signal));
  const save = async () => {
    if (draft !== (cutoff ?? '') && (await action.execute(draft))) onSaved();
  };
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <TextField
        type="date"
        label={t('Decision cutoff')}
        value={draft}
        onChange={setDraft}
        onBlur={save}
        isDisabled={disabled || action.pending}
        errorMessage={action.error ? t('The cutoff was not saved.') : undefined}
        className="w-44"
      />
    </form>
  );
}

interface EditorProps {
  item: Item;
  projectId: string;
  knownIds: Set<string>;
  onSaved: (saved: Clarification) => void;
  onOpenRisk: (item: Item) => void;
  close: () => void;
}

/**
 * The fields of one clarification. Save replaces them (a question not raised yet is raised with
 * them); "Save as new" raises another clarification on the same risk (a second party to ask),
 * which the server refuses to duplicate while one of the same type is undecided.
 */
function Editor({ item, projectId, knownIds, onSaved, onOpenRisk, close }: EditorProps) {
  const [form, setForm] = useState<Pick<Clarification, 'kind' | 'title' | 'status' | 'phase' | 'answer'> & { due: string }>({
    kind: item.kind,
    title: item.title,
    status: item.status,
    due: item.due ?? '',
    phase: item.phase,
    answer: item.answer,
  });
  const [notice, setNotice] = useState<string | null>(null);
  const set = (field: keyof typeof form) => (value: string) => setForm((current) => ({ ...current, [field]: value }));
  const title = form.title.trim();
  const fields = { ...form, title, due: form.due || null };
  const raised = item.clarification_id !== null;
  const action = useAsyncAction((signal, asNew: boolean) =>
    asNew || !raised
      ? createClarification(projectId, { ...fields, document_id: item.document_id, risk_id: item.risk_id, tier: item.tier }, signal)
      : // Only reached once raised, so it has an id.
        saveClarification(item.clarification_id!, fields, signal),
  );
  const submit = async (asNew: boolean) => {
    setNotice(null);
    const saved = await action.execute(asNew);
    if (!saved) return;
    if (asNew && knownIds.has(saved.clarification_id)) {
      setNotice(t('This risk already has an open clarification of this type. Choose another type to add a second one.'));
      return;
    }
    onSaved(saved);
    close();
  };
  const sent = kindOf(form.kind).sent;

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        submit(false);
      }}
    >
      <TextField label={t('Item')} value={form.title} onChange={set('title')} maxLength={300} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Select label={t('Type')} value={form.kind} options={KINDS.map((kind) => ({ ...kind, label: t(kind.label) }))} onChange={set('kind')} />
        <Select
          label={t('Status')}
          value={form.status}
          options={STATUSES.map((status) => ({ ...status, label: t(status.value === 'sent' ? sent : status.label) }))}
          onChange={set('status')}
        />
        <TextField type="date" label={t('Answer needed by')} value={form.due} onChange={set('due')} />
        <Select label={t('Phase')} value={form.phase} options={PHASES.map((option) => ({ ...option, label: t(option.label) }))} onChange={set('phase')} />
      </div>
      <TextField label={t('Answer')} multiline rows={3} value={form.answer} onChange={set('answer')} maxLength={4000} />
      {item.subject && (
        <section aria-label={t('Email')} className="space-y-1 rounded-md border border-hairline bg-surface-muted p-3">
          <p className="text-caption text-ink-secondary">
            {item.sent_at ? t('Email sent {day}', { day: formatSent(item.sent_at) }) : t('Email drafted, not sent yet')}
            {item.recipient ? `, ${t('to {recipient}', { recipient: item.recipient })}` : ''}
          </p>
          <p className="text-callout font-semibold">{item.subject}</p>
          {item.body && <p className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words text-callout">{item.body}</p>}
        </section>
      )}
      {notice && (
        <p role="alert" className="text-callout text-ink">
          {notice}
        </p>
      )}
      {action.error && <ErrorState error={action.error} title={t('The clarification was not saved')} compact />}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" variant="primary" loading={action.pending} isDisabled={!title}>
          {t('Save')}
        </Button>
        {raised && (
          <Button isDisabled={action.pending || !title} onPress={() => submit(true)}>
            {t('Save as new')}
          </Button>
        )}
        <Button variant="ghost" className="ml-auto" onPress={() => onOpenRisk(item)}>
          {t('Open the risk')}
        </Button>
      </div>
    </form>
  );
}

interface ClarificationsPanelProps {
  projectId: string;
  /** The project's `decision_cutoff`, `YYYY-MM-DD`. */
  cutoff?: string | null;
  /** The project's files, for the bills' names; null while the project loads. */
  documents: { document_id: string; original_filename: string }[] | null;
  disabled?: boolean;
  /** Opens a clarification's risk in the Workspace. */
  onOpenRisk: (item: Item) => void;
  onCutoffSaved: () => void;
}

/**
 * The Clarifications of a project: the questions to settle before the bid decision. Each risk of
 * the project's last validation that asks the client a question is listed as a draft question
 * to the client until a reviewer saves it; a risk marked "Needs clarification" in the Workspace
 * is listed too, and so is an email drafted about a risk, with its recipient and the day it was
 * sent (opened in an email app or copied). On top the day of the bid decision; then the list,
 * with a search and filters above it, which the server pages, searches and filters. A row opens
 * its fields: who is asked, how far it is, the day its answer is needed and the answer. The page
 * is one window tall, a page of the list holding as many rows as fit, at most 10; while a page
 * loads, its rows are grey.
 *
 * `disabled` locks the cutoff while the project is validated: that job writes the project too.
 */
export function ClarificationsPanel({
  projectId,
  cutoff = null,
  documents,
  disabled = false,
  onOpenRisk,
  onCutoffSaved,
}: ClarificationsPanelProps) {
  const [filters, setFilters] = useState<ClarificationFilters>(NO_CLARIFICATION_FILTERS);
  const [offset, setOffset] = useState(0);
  const [fittingRows, setFittingRows] = useState(PAGE_SIZE);
  const pageSize = Math.min(fittingRows, PAGE_SIZE);
  const search = useDebouncedValue(filters.search, SEARCH_DELAY_MS);
  const resource = useClarificationPage(projectId, { ...clarificationQuery({ ...filters, search }), offset, limit: pageSize });
  const page = resource.data;
  const [editing, setEditing] = useState<Item | null>(null);
  const billNames = useMemo(() => new Map((documents ?? []).map((doc) => [doc.document_id, doc.original_filename])), [documents]);
  const billName = (item: Item) => billNames.get(item.document_id) ?? t('A file no longer in the project');
  const changeFilters = (next: ClarificationFilters) => {
    setFilters(next);
    setOffset(0);
  };
  const columns: DataTableColumn<Item>[] = [
    {
      key: 'kind',
      header: t('Type'),
      render: (item) => <Badge tone={kindOf(item.kind).tone}>{t(kindOf(item.kind).label)}</Badge>,
    },
    {
      key: 'title',
      header: t('Item'),
      className: 'max-w-0 w-full',
      render: (item) => (
        <>
          <span className="block truncate" title={item.title}>
            {item.title}
          </span>
          <span className="block truncate text-caption text-ink-secondary">{billName(item)}</span>
        </>
      ),
    },
    { key: 'recipient', header: t('Recipient'), className: 'max-w-48 truncate text-ink-secondary', render: (item) => item.recipient || '—' },
    { key: 'status', header: t('Status'), className: 'whitespace-nowrap', render: (item) => <ClarificationStatusSelect item={item} onSaved={resource.reload} /> },
    { key: 'sent', header: t('Sent'), className: 'whitespace-nowrap tabular-nums', render: (item) => formatSent(item.sent_at) || '—' },
    { key: 'due', header: t('Due'), className: 'whitespace-nowrap tabular-nums', render: (item) => formatDay(item.due) || '—' },
    {
      key: 'left',
      header: t('Time left'),
      className: 'whitespace-nowrap text-caption',
      render: (item) => {
        const note = dueNote(item, cutoff);
        return note && <span className={note.urgent ? 'font-medium text-danger' : 'text-ink-secondary'}>{note.text}</span>;
      },
    },
    {
      key: 'open',
      header: t('Risk'),
      className: 'whitespace-nowrap',
      render: (item) => (
        <Button variant="link" className="whitespace-nowrap!" onPress={() => onOpenRisk(item)}>
          {t('Open the risk')}
        </Button>
      ),
    },
  ];

  const failed = Boolean(resource.error && !page);
  const loading = (!page && !failed) || documents === null;
  const empty = !loading && page?.total === 0;
  const noMatch = empty && hasClarificationFilters(filters);
  let status: string | null = null;
  if (failed) status = t('The clarifications could not be loaded');
  else if (noMatch) status = t('No clarifications match the search and filters');
  else if (empty) status = t('No clarifications yet');

  return (
    <div className="flex h-project-page min-h-fit flex-col gap-4">
      <CutoffField key={cutoff ?? ''} projectId={projectId} cutoff={cutoff} disabled={disabled || documents === null} onSaved={onCutoffSaved} />
      <div className="flex-1">
        <TableCard
          title={t('Clarifications')}
          count={loading || !page ? null : page.total}
          summary={<ClarificationFilterBar filters={filters} onChange={changeFilters} />}
          columns={columns}
          rows={page?.items ?? []}
          getRowKey={clarificationKey}
          caption={t('Clarifications')}
          onRowActivate={setEditing}
          pageSize={pageSize}
          rowHeight={TWO_LINE_ROW_REM}
          fill
          onPageSizeChange={setFittingRows}
          offset={offset}
          total={page?.total ?? 0}
          onOffsetChange={setOffset}
          itemLabel={page?.total === 1 ? t('clarification') : t('clarifications')}
          status={status}
          statusAction={
            (failed && (
              <Button icon={RotateCw} onPress={resource.reload}>
                {t('Retry')}
              </Button>
            )) ||
            (noMatch && <Button onPress={() => changeFilters(NO_CLARIFICATION_FILTERS)}>{t('Clear filters')}</Button>)
          }
          loading={loading}
          loadingLabel={t('Loading the clarifications…')}
        />
      </div>
      {editing && (
        <Dialog open onOpenChange={(open) => !open && setEditing(null)} title={t('Clarification')} description={billName(editing)}>
          {({ close }) => (
            <Editor
              item={editing}
              projectId={projectId}
              knownIds={new Set((page?.items ?? []).map((item) => item.clarification_id).filter((id): id is string => Boolean(id)))}
              onSaved={(saved) => {
                resource.setData((current) => current && withSaved(current, saved));
                resource.reload();
              }}
              onOpenRisk={onOpenRisk}
              close={close}
            />
          )}
        </Dialog>
      )}
    </div>
  );
}
