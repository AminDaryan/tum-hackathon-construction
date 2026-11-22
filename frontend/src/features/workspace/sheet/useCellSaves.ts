import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ApiError } from '../../../services/apiClient.ts';
import type { CorrectionsResult } from '../../../services/apiTypes.ts';
import { correctCells } from '../../../services/datasetsService.ts';
import { describeError } from '../../../utils/errors.ts';
import { cellKey } from './sheetMoves.ts';

function isConflict(error: unknown): error is ApiError {
  return error instanceof ApiError && (error.status === 409 || error.code === 'conflict');
}

/** One cell edit to save; `before` is the text it replaces, kept for Undo. */
interface CellEdit {
  rowId: string;
  columnId: string;
  reference: string;
  before: string;
  text: string;
  undo?: boolean;
}

/** The outcome of the last save, for the footer. */
export type SaveOutcome =
  | { kind: 'saving' | 'unchanged'; reference: string }
  | { kind: 'saved'; reference: string; revision: number; caveat: boolean; undo: CellEdit }
  | { kind: 'restored'; reference: string; revision: number }
  | { kind: 'conflict'; reference: string; currentRevision: number | null }
  | { kind: 'error'; reference: string; message: string };

/**
 * Saves cell edits one at a time, each as the dataset's next revision. Saves wait for the one
 * before, so a quick second edit is sent with the revision the first one produced.
 *
 * - `pending`: the text being saved, by {@link cellKey}, shown dimmed until the answer comes.
 * - `status`: the last outcome for the footer: `saving`, `saved` (with the edit to undo),
 *   `restored` (an undo was saved), `unchanged`, `conflict` (409, with the server's revision)
 *   or `error`.
 * - `save(edit)`: `{ rowId, columnId, reference, before, text, undo? }`.
 * - `undo()`: sends the text before the last saved edit back as one more correction.
 * - `acceptReload()`: after a conflict, continue from the server's revision.
 */
export function useCellSaves({
  datasetId,
  tableId,
  revision,
  onSaved,
}: {
  datasetId: string;
  tableId: string;
  revision: number;
  onSaved: (result: CorrectionsResult) => void;
}) {
  const revisionRef = useRef(revision);
  const queueRef = useRef(Promise.resolve());
  const firstSaveRef = useRef(true);
  const onSavedRef = useRef(onSaved);
  const [pending, setPending] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<SaveOutcome | null>(null);

  useLayoutEffect(() => {
    onSavedRef.current = onSaved;
  });
  useEffect(() => {
    revisionRef.current = revision;
  }, [revision]);

  const save = useCallback(
    ({ rowId, columnId, reference, before, text, undo = false }: CellEdit) => {
      const key = cellKey(rowId, columnId);
      setPending((current) => ({ ...current, [key]: text }));
      setStatus({ kind: 'saving', reference });
      const run = async () => {
        try {
          const result = await correctCells(datasetId, {
            expectedRevision: revisionRef.current,
            corrections: [{ table_id: tableId, row_id: rowId, column_id: columnId, raw_value: text }],
          });
          if (!result.changed) {
            setStatus({ kind: 'unchanged', reference });
            return;
          }
          revisionRef.current = result.revision;
          onSavedRef.current(result);
          if (undo) {
            setStatus({ kind: 'restored', reference, revision: result.revision });
          } else {
            const caveat = firstSaveRef.current;
            firstSaveRef.current = false;
            setStatus({
              kind: 'saved',
              reference,
              revision: result.revision,
              caveat,
              undo: { rowId, columnId, reference, before: text, text: before },
            });
          }
        } catch (error) {
          if (isConflict(error)) {
            const current = error.details?.current_revision;
            setStatus({ kind: 'conflict', reference, currentRevision: typeof current === 'number' && Number.isInteger(current) ? current : null });
          } else {
            const { message, hint } = describeError(error);
            setStatus({ kind: 'error', reference, message: hint ? `${message} ${hint}` : message });
          }
        } finally {
          setPending((current) => {
            const next = { ...current };
            delete next[key];
            return next;
          });
        }
      };
      queueRef.current = queueRef.current.then(run);
    },
    [datasetId, tableId],
  );

  const undo = useCallback(() => {
    if (status?.kind === 'saved') {
      save({ ...status.undo, undo: true });
    }
  }, [save, status]);

  const acceptReload = useCallback(() => {
    if (status?.kind === 'conflict' && status.currentRevision) {
      revisionRef.current = status.currentRevision;
    }
    setStatus(null);
  }, [status]);

  return { pending, status, save, undo, acceptReload };
}
