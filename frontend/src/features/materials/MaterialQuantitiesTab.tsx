import { ChevronRight, Info } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button as AriaButton } from 'react-aria-components';
import { Button } from '../../components/Button.tsx';
import { Checkbox } from '../../components/Checkbox.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { SearchField } from '../../components/Field.tsx';
import { LoadingState } from '../../components/LoadingState.tsx';
import { Pagination } from '../../components/Pagination.tsx';
import { Tooltip } from '../../components/Tooltip.tsx';
import { t } from '../../i18n/messages.ts';
import { cx } from '../../utils/classNames.ts';
import { formatCount, formatDecimal } from '../../utils/format.ts';
import { saveBlob } from '../../utils/download.ts';
import { readStorage, writeStorage } from '../../utils/safeStorage.ts';
import { EmailDraftButton } from '../email/EmailDraft.tsx';
import { supplierEmailDraft } from '../email/emailDraft.ts';
import type { DatasetSummary } from '../../services/apiTypes.ts';
import { loadMaterialQuantities } from './loadMaterialQuantities.ts';
import { materialQuantitiesCsv, mergeMaterialGroups, type MaterialGroup, type MaterialPosition } from './materialQuantities.ts';

const PAGE = 40;

interface MaterialQuantitiesTabProps {
  dataset: Pick<DatasetSummary, 'dataset_id' | 'tables'>;
  revision: number;
  billName: string;
  onShowPosition: (position: MaterialPosition) => void;
}

/**
 * Bill-wide material quantities: search, the actions with their scope and the merge bar on top,
 * a compact list of groups below that scrolls on its own. Reviewer merges are kept for this browser
 * tab and this bill revision (replayed on the loaded groups), so leaving the tab keeps them; the
 * parent remounts the tab on a new revision, and changed specifications start over.
 */
export function MaterialQuantitiesTab({ dataset, revision, billName, onShowPosition }: MaterialQuantitiesTabProps) {
  const mergesKey = `twb.materialMerges.v1.${dataset.dataset_id}.${revision}`;
  const [result, setResult] = useState<{ groups: MaterialGroup[]; skipped: number } | null>(null);
  const [merges, setMerges] = useState<string[][]>(() => {
    try {
      const stored: unknown = JSON.parse(readStorage(mergesKey, 'session') ?? '[]');
      return Array.isArray(stored) ? (stored as string[][]) : [];
    } catch { return []; }
  });
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [openId, setOpenId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    setError(null);
    loadMaterialQuantities(dataset, controller.signal).then((loaded) => {
      if (controller.signal.aborted) return;
      setResult(loaded);
      setSelected(new Set());
      setOffset(0);
    }).catch((failure: Error) => { if (!controller.signal.aborted) setError(failure); });
    return () => controller.abort();
  }, [dataset, attempt]);
  useEffect(() => {
    writeStorage(mergesKey, merges.length ? JSON.stringify(merges) : null, 'session');
  }, [mergesKey, merges]);
  const groups = useMemo(
    () => (result ? merges.reduce((current, ids) => mergeMaterialGroups(current, new Set(ids)), result.groups) : []),
    [result, merges],
  );
  const chosen = groups.filter((group) => selected.has(group.id));
  const output = chosen.length ? chosen : groups;
  const draft = useMemo(() => supplierEmailDraft({ groups: output, billName }), [output, billName]);
  const canMerge = chosen.length > 1 && new Set(chosen.map((group) => group.unit)).size === 1;
  const needle = search.trim().toLowerCase();
  const shown = needle ? groups.filter((group) => group.description.toLowerCase().includes(needle)) : groups;
  const toggle = (id: string, checked: boolean) => setSelected((current) => {
    const next = new Set(current);
    if (checked) next.add(id); else next.delete(id);
    return next;
  });
  if (error) return <div className="p-3"><ErrorState error={error} title={t('Material quantities could not be loaded')} onRetry={() => setAttempt(attempt + 1)} /></div>;
  if (!result) return <div className="p-3"><LoadingState label={t('Loading all bill positions…')} /></div>;
  if (!groups.length) return <p className="p-3 text-body">{t('No eligible quantity positions in this bill.')}</p>;
  return (
    <section aria-label={t('Material quantities')} className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-2 border-b border-hairline px-3 py-2">
        <div className="flex items-center gap-1">
          <p role="status" className="text-callout text-ink-secondary">
            {t('{groups} groups. {skipped} positions omitted.', { groups: formatCount(groups.length), skipped: formatCount(result.skipped) })}
          </p>
          <Tooltip content={t('Only identical specification text, section context and units are grouped. Omitted: excluded, optional or uncertain positions, and positions without quantity, description or unit.')}>
            <AriaButton aria-label={t('About material quantities')} className="flex size-6 items-center justify-center rounded-md text-ink-tertiary hover:bg-state-hover">
              <Info aria-hidden="true" className="size-4" />
            </AriaButton>
          </Tooltip>
        </div>
        <SearchField label={t('Search materials')} placeholder={t('Search materials')} value={search} onChange={(value) => { setSearch(value); setOffset(0); }} />
        <div className="flex flex-wrap items-center gap-2">
          <EmailDraftButton draft={draft} label={t('Request supplier prices')} title={t('Supplier price request')} />
          <Button onPress={() => {
            saveBlob(new Blob([materialQuantitiesCsv(output)], { type: 'text/csv;charset=utf-8' }), 'material-quantities.csv');
            setNotice(t('Downloaded material-quantities.csv'));
          }}>{t('Export quantities as CSV')}</Button>
          <span className="text-caption text-ink-secondary">
            {chosen.length ? t('{count} selected', { count: formatCount(chosen.length) }) : t('All {count} groups', { count: formatCount(groups.length) })}
          </span>
        </div>
        {(selected.size > 0 || merges.length > 0) && (
          <div className="flex flex-wrap items-center gap-2 rounded-md bg-surface-subtle px-2 py-1">
            <Button variant="primary" isDisabled={!canMerge} onPress={() => {
              setMerges([...merges, chosen.map((group) => group.id)]);
              setSelected(new Set());
              setOffset(0);
            }}>{t('Confirm same spec and merge')}</Button>
            {selected.size > 0 && <Button variant="ghost" onPress={() => setSelected(new Set())}>{t('Clear selection')}</Button>}
            {merges.length > 0 && <Button variant="ghost" onPress={() => { setMerges([]); setSelected(new Set()); setOffset(0); }}>{t('Reset merges')}</Button>}
          </div>
        )}
        {notice && <p className="text-caption text-ink-secondary" aria-live="polite">{notice}</p>}
      </div>
      <div className="relative min-h-0 flex-1 overflow-y-auto px-3">
        {shown.length > PAGE && <Pagination offset={offset} limit={PAGE} total={shown.length} onChange={setOffset} itemLabel={t('material groups')} />}
        <ul aria-label={t('Material groups')} className="divide-y divide-hairline">
          {shown.slice(offset, offset + PAGE).map((group) => {
            const open = openId === group.id;
            return (
              <li key={group.id} className="py-0.5">
                <div className="flex items-center gap-1">
                  <Checkbox className="min-w-0 flex-1 [&>span:last-child]:flex-1" checked={selected.has(group.id)} onChange={(checked) => toggle(group.id, checked)}>
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate">{group.description}</span>{' '}
                      <span className="shrink-0 tabular-nums font-medium text-accent-strong">{formatDecimal(group.quantity)} {group.unit}</span>
                    </span>
                  </Checkbox>
                  <AriaButton
                    aria-label={t('Contributing positions ({count})', { count: formatCount(group.positions.length) })}
                    aria-expanded={open}
                    onPress={() => setOpenId(open ? null : group.id)}
                    className="flex h-8 shrink-0 items-center gap-0.5 rounded-md px-1 text-caption text-ink-secondary hover:bg-state-hover"
                  >
                    {formatCount(group.positions.length)}
                    <ChevronRight aria-hidden="true" className={cx('size-4 transition-transform', open && 'rotate-90')} />
                  </AriaButton>
                </div>
                {group.reviewed && <p className="pl-7 text-caption text-ink-secondary">{t('Merged by reviewer')}</p>}
                {open && (
                  <ul className="space-y-1 pb-1 pl-7">
                    {group.positions.map((position) => (
                      <li key={position.id} className="text-caption">
                        <Button variant="link" onPress={() => onShowPosition(position)}>{t('{table}, position {position}, row {row}', { table: position.tableName, position: position.code || '—', row: position.rowNumber })}</Button>
                        <span className="ml-2 tabular-nums">{formatDecimal(position.quantity)} {group.unit}</span>
                        <p className="whitespace-pre-wrap break-words text-ink-secondary">{position.specification}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
          {!shown.length && <li className="py-3 text-callout text-ink-secondary">{t('No materials match.')}</li>}
        </ul>
      </div>
    </section>
  );
}
