import { Info, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button as AriaButton } from 'react-aria-components';
import { Button } from '../../components/Button.tsx';
import { Checkbox } from '../../components/Checkbox.tsx';
import { ComboBox } from '../../components/ComboBox.tsx';
import { IconButton } from '../../components/IconButton.tsx';
import { SearchField, TextField } from '../../components/Field.tsx';
import { Select } from '../../components/Select.tsx';
import { Tooltip } from '../../components/Tooltip.tsx';
import { t } from '../../i18n/messages.ts';
import { getTableRows } from '../../services/datasetsService.ts';
import { getDocument } from '../../services/documentsService.ts';
import { cx } from '../../utils/classNames.ts';
import { parseDecimal } from '../../utils/decimal.ts';
import { formatDecimal, pluralize } from '../../utils/format.ts';
import { readStorage, writeStorage } from '../../utils/safeStorage.ts';
import type { DatasetSummary, Row, TableSummary } from '../../services/apiTypes.ts';
import { matchesMaterial } from '../materials/materialMatching.ts';
import { materialQuantities } from '../materials/materialQuantities.ts';
import { evaluateScenario, scenarioPositions, type ScenarioResult, type ScenarioRule } from './scenarios.ts';

/** A scenario saved in this browser, bound to the bill revision it was made on. */
interface SavedScenario {
  name: string;
  version: number;
  datasetId: string;
  revision: number;
  rules: ScenarioRule[];
  inclusion: Record<string, boolean | null>;
  result: ScenarioResult;
  createdAt: string;
}

interface WhatIfTabProps {
  dataset: Pick<DatasetSummary, 'dataset_id' | 'document_id' | 'tables'>;
  revision: number;
}

interface WhatIfDraft {
  materialId: string;
  query: string;
  percent: string;
  selected: string[];
  rules: ScenarioRule[];
  inclusion: Record<string, boolean | null>;
  name: string;
}

const EMPTY_DRAFT: WhatIfDraft = { materialId: '', query: '', percent: '15', selected: [], rules: [], inclusion: {}, name: '' };

function readJson<T>(key: string, area: 'local' | 'session', fallback: T): T {
  try {
    return (JSON.parse(readStorage(key, area) ?? 'null') as T | null) ?? fallback;
  } catch {
    return fallback;
  }
}

/**
 * Bill-wide what-if: a pinned summary (before, after, change) with the price rule and saved
 * scenarios over a compact list of positions that scrolls on its own. The working draft is kept
 * for this browser tab (switching panel tabs or reloading keeps it); named versions are kept in
 * this browser. Local snapshots are deliberately not correction revisions and never call a write API.
 */
export function WhatIfTab({ dataset, revision }: WhatIfTabProps) {
  const [tables, setTables] = useState<(TableSummary & { rows: Row[] })[] | null>(null);
  const [error, setError] = useState(false);
  const draftKey = `twb.whatIf.draft.v1.${dataset.dataset_id}.${revision}`;
  const [draft, setDraft] = useState<WhatIfDraft>(() => ({ ...EMPTY_DRAFT, ...readJson<Partial<WhatIfDraft>>(draftKey, 'session', {}) }));
  const { materialId, query, percent, selected, rules, inclusion, name } = draft;
  const update = (change: Partial<WhatIfDraft>) => setDraft((current) => ({ ...current, ...change }));
  const [saved, setSaved] = useState('');
  const [search, setSearch] = useState('');
  const [show, setShow] = useState('all');
  const [openKey, setOpenKey] = useState<string | null>(null);
  const storageKey = `twb.whatIf.v1.${dataset.dataset_id}.${revision}`;
  const [versions, setVersions] = useState<SavedScenario[]>(() => {
    const stored = readJson<unknown>(storageKey, 'local', []);
    // Written by save() below under this key.
    return Array.isArray(stored) ? (stored as SavedScenario[]) : [];
  });
  useEffect(() => {
    writeStorage(draftKey, JSON.stringify(draft), 'session');
  }, [draftKey, draft]);
  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    async function load() {
      try {
        const result: (TableSummary & { rows: Row[] })[] = [];
        for (const table of dataset.tables) {
          const rows: Row[] = [];
          let total: number;
          do {
            const page = await getTableRows(dataset.dataset_id, table.table_id, { offset: rows.length, limit: 1000 }, { signal });
            if (!page.items.length && rows.length < page.total) throw new Error('Incomplete page');
            rows.push(...page.items);
            total = page.total;
          } while (rows.length < total);
          result.push({ ...table, rows });
        }
        // Row APIs read the latest revision. Reject a mixed or stale snapshot after paging.
        const latest = await getDocument(dataset.document_id, { signal });
        if (latest.dataset?.revision !== revision) throw new Error('Revision changed');
        if (!signal.aborted) setTables(result);
      } catch {
        if (!signal.aborted) setError(true);
      }
    }
    load();
    return () => controller.abort();
  }, [dataset.dataset_id, dataset.document_id, dataset.tables, revision]);
  const positions = useMemo(() => tables ? scenarioPositions(tables) : [], [tables]);
  const groups = useMemo(() => tables ? materialQuantities(tables.map((table) => ({ table, rows: table.rows }))).groups : [], [tables]);
  const materials = useMemo(() => groups.map((group) => ({ value: group.id,
    label: `${group.description}, ${group.unit} (${group.positions[0].code || group.positions[0].rowNumber})`,
  })), [groups]);
  const result = useMemo(() => evaluateScenario(positions, rules, inclusion), [positions, rules, inclusion]);
  const parsed = parseDecimal(percent);
  const valid = parsed && parsed.units >= -100n * 10n ** BigInt(parsed.scale);
  const money = (value: string | null | undefined) => value == null ? t('Not given') : `${formatDecimal(value)}${result.currency ? ` ${result.currency}` : ''}`;
  const save = () => {
    const version = versions.filter((entry) => entry.name === name.trim()).length + 1;
    const entry: SavedScenario = { name: name.trim(), version, datasetId: dataset.dataset_id, revision, rules, inclusion,
      result, createdAt: new Date().toISOString() };
    const next = [...versions, entry];
    if (writeStorage(storageKey, JSON.stringify(next))) {
      setVersions(next);
      setSaved(t('Saved locally as version {version}.', { version }));
    } else { setSaved(t('Could not save locally. Browser storage may be full or disabled.')); }
  };
  if (error) return <p role="alert" className="p-3">{t('Could not load a consistent bill revision. Reopen the file and try again.')}</p>;
  if (!tables) return <p role="status" className="p-3">{t('Loading all bill positions…')}</p>;
  const needle = search.trim().toLowerCase();
  const shown = result.rows.filter((position) =>
    (show === 'all' || (show === 'changed' && position.affected) || (show === 'optional' && position.sourceIncluded !== true)
      || (show === 'matches' && selected.includes(position.key)))
    && (!needle || `${position.itemCode ?? ''} ${position.text}`.toLowerCase().includes(needle)));
  const choosing = Boolean(materialId) || selected.length > 0;
  return (
    <section aria-label={t('What-if')} className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-2 border-b border-hairline px-3 py-2">
        <div className="rounded-md bg-surface-subtle px-3 py-2" aria-live="polite">
          <div className="flex items-center gap-1">
            <h2 className="text-callout font-semibold">{t('Net bid comparison')}</h2>
            <Tooltip content={t('Preview only. The BoQ is never changed. Net position totals exclude tax and bill-level adjustments. Unknown currencies are not inferred.')}>
              <AriaButton aria-label={t('About what-if')} className="flex size-6 items-center justify-center rounded-md text-ink-tertiary hover:bg-state-hover">
                <Info aria-hidden="true" className="size-4" />
              </AriaButton>
            </Tooltip>
          </div>
          <dl className="grid grid-cols-3 gap-2 text-callout sheet-figures">
            <div className="min-w-0 break-words"><dt className="text-caption text-ink-secondary">{t('Before')}</dt><dd>{money(result.before)}</dd></div>
            <div className="min-w-0 break-words"><dt className="text-caption text-ink-secondary">{t('After')}</dt><dd>{money(result.after)}</dd></div>
            <div className="min-w-0 break-words"><dt className="text-caption text-ink-secondary">{t('Change')}</dt><dd className="font-semibold">{money(result.change)}</dd></div>
          </dl>
          {!result.complete && <p className="mt-1 text-caption text-danger">{t('No reliable bid total: check missing prices, inconsistent line totals, unknown inclusion or mixed currencies. No partial total is presented as a bid total.')}</p>}
        </div>
        <div className="flex items-end gap-2">
          <ComboBox className="min-w-0 flex-1" label={t('Material or specification')} value={materialId} options={materials} onChange={(value) => {
            if (!value) {
              update({ materialId: '', query: '' });
              if (show === 'matches') setShow('all');
              return;
            }
            const group = groups.find((candidate) => candidate.id === value);
            const keys = new Set(group?.positions.map((position) => position.id));
            update({ materialId: value, query: group?.description ?? '',
              selected: group ? positions.filter((position) => keys.has(position.key) && matchesMaterial(position.text, group.description)).map((position) => position.key) : [] });
            if (group) setShow('matches');
          }} placeholder={t('Choose a material group')} />
          {materialId && <IconButton icon={X} label={t('Clear material or specification')} onPress={() => {
            update({ materialId: '', query: '' });
            if (show === 'matches') setShow('all');
          }} />}
          <TextField className="w-40 shrink-0" label={t('Unit price change (%)')} placeholder="%" value={percent} maxLength={30} inputMode="decimal" onChange={(value) => update({ percent: value })} />
          <Button className="shrink-0" variant="primary" isDisabled={!valid || !selected.length} onPress={() => {
            update({ rules: [...rules, { query, percent, keys: [...selected] }], materialId: '', query: '', selected: [] });
            setShow('all');
            setSaved('');
          }}>{t('Add price rule')}</Button>
        </div>
        {!valid && <p role="alert" className="text-caption text-danger">{t('Enter a percentage of at least −100.')}</p>}
        {(rules.length > 0 || choosing) && (
          <ul aria-label={t('Price rules')} className="flex flex-wrap items-center gap-1.5 text-callout">
            {rules.map((rule, index) => (
              <li key={index} className="flex items-center gap-1 rounded-md border border-hairline bg-surface pl-2">
                <span>{rule.query || t('Manual selection')}: {rule.percent}% ({rule.keys.length})</span>
                <IconButton icon={X} label={t('Remove rule {number}', { number: index + 1 })} onPress={() => { update({ rules: rules.filter((_, i) => i !== index) }); setSaved(''); }} />
              </li>
            ))}
            {choosing && <li className="text-caption text-ink-secondary">{t('{positions} selected', { positions: pluralize(selected.length, 'position') })}</li>}
          </ul>
        )}
        <div className="flex items-end gap-2">
          <TextField className="min-w-0 flex-1" label={t('Scenario name')} hideLabel placeholder={t('Scenario name')} value={name} maxLength={120} onChange={(value) => update({ name: value })} />
          <Button className="shrink-0" isDisabled={!name.trim() || !result.complete} onPress={save}>{t('Save scenario')}</Button>
          {versions.length > 0 && <Select className="w-40 shrink-0" label={t('Load saved version')} hideLabel value="" options={[{ value: '', label: t('Saved ({count})', { count: versions.length }) }, ...versions.map((entry, index) => ({ value: String(index), label: `${entry.name} / v${entry.version}` }))]}
            onChange={(value) => {
              if (!value) return;
              const entry = versions[Number(value)];
              update({ name: entry.name, rules: entry.rules, inclusion: entry.inclusion });
              setSaved(t('Loaded {name} / v{version}.', { name: entry.name, version: entry.version }));
            }} />}
        </div>
        {saved && <p role="status" className="text-caption text-ink-secondary">{saved}</p>}
        <div className="flex items-center gap-2">
          <SearchField className="min-w-0 flex-1" label={t('Search positions')} placeholder={t('Search positions')} value={search} onChange={setSearch} />
          <Select className="w-44 shrink-0" label={t('Show')} hideLabel value={show} onChange={setShow} options={[
            { value: 'all', label: t('All positions ({count})', { count: result.rows.length }) },
            { value: 'changed', label: t('Changed') },
            { value: 'optional', label: t('Optional and alternatives') },
            { value: 'matches', label: t('Rule matches') },
          ]} />
        </div>
      </div>
      <ul aria-label={t('Positions')} className="relative min-h-0 flex-1 divide-y divide-hairline overflow-y-auto px-3">
        {shown.map((position) => {
          const open = openKey === position.key;
          return (
            <li key={position.key} className={cx('py-1', position.affected && 'bg-state-selected/40')}>
              <div className="flex items-center gap-2">
                {!choosing && <Checkbox checked={position.included === true} onChange={(checked) => { update({ inclusion: { ...inclusion, [position.key]: checked } }); setSaved(''); }}>
                  <span className="sr-only">{t('Include in scenario bid')}</span>
                </Checkbox>}
                {choosing && (
                  <Checkbox checked={selected.includes(position.key)} onChange={(checked) => update({ selected: checked ? [...selected, position.key] : selected.filter((key) => key !== position.key) })}>
                    <span className="sr-only">{t('Price rule match')}</span>
                  </Checkbox>
                )}
                <button type="button" aria-expanded={open} onClick={() => setOpenKey(open ? null : position.key)} className="flex min-w-0 flex-1 items-baseline gap-2 rounded-sm text-left text-callout hover:bg-state-hover">
                  <span className="shrink-0 text-caption text-ink-secondary sheet-figures">{position.itemCode || position.rowId}</span>
                  <span className="min-w-0 flex-1 truncate">{position.text || t('No description')}</span>
                </button>
                <span className={cx('shrink-0 text-callout sheet-figures', position.change && position.change !== '0.00' ? 'font-semibold' : 'text-ink-tertiary')}>
                  {position.affected ? money(position.change) : formatDecimal(position.oldTotal ?? '') || '—'}
                </span>
              </div>
              {position.sourceIncluded === null && <p className="pl-7 text-caption text-danger">{t('Source inclusion is unknown; the before total cannot be established.')}</p>}
              {!position.reliable && <p className="pl-7 text-caption text-danger">{t('Source line total does not follow quantity × unit price with discount. Resolve it before simulating a price change.')}</p>}
              {open && (
                <div className="space-y-0.5 pb-1 pl-7 text-caption text-ink-secondary sheet-figures">
                  <p className="whitespace-pre-line text-ink">{position.text}</p>
                  <p>{position.tableName}</p>
                  <p>{t('Unit price')}: {money(position.unitPrice)} → {money(position.price)}</p>
                  <p>{t('Bid contribution')}: {money(position.oldTotal)} → {money(position.newTotal)}</p>
                </div>
              )}
            </li>
          );
        })}
        {!shown.length && <li className="py-3 text-callout text-ink-secondary">{t('No positions match.')}</li>}
      </ul>
    </section>
  );
}
