import { useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';

const MAX_ROWS = 6;

export interface CellEditorProps {
  label: string;
  initialText: string;
  selectAll: boolean;
  onCommit: (text: string, move: 'left' | 'right' | null, options: { viaBlur: boolean }) => void;
  onCancel: () => void;
}

/**
 * The in-cell text field. It covers the cell (at least 160 px wide), one line high for
 * single-line text and up to six lines for text with line breaks. The cell's text is selected
 * when editing starts with Enter, F2 or a double-click; editing started by typing begins with
 * the typed character.
 *
 * Enter saves, Shift+Enter adds a line break, Escape cancels, Tab and Shift+Tab save and move
 * right or left, and leaving the field saves. `onCommit(text, move, { viaBlur })` is called at
 * most once, as is `onCancel()`.
 */
export function CellEditor({ label, initialText, selectAll, onCommit, onCancel }: CellEditorProps) {
  const [text, setText] = useState(initialText);
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const doneRef = useRef(false);

  useLayoutEffect(() => {
    const field = fieldRef.current;
    if (!field) return;
    field.focus({ preventScroll: true });
    if (selectAll) {
      field.select();
    } else {
      field.setSelectionRange(field.value.length, field.value.length);
    }
    // Only when the editor opens.
  }, []);

  const commit = (move: 'left' | 'right' | null, viaBlur = false) => {
    if (doneRef.current) return;
    doneRef.current = true;
    onCommit(text, move, { viaBlur });
  };
  const cancel = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    onCancel();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // The grid's own keys (arrows, Home, End, typing) must not act while the field is open.
    event.stopPropagation();
    if (event.key === 'Enter' && !event.shiftKey && !event.altKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      commit(null);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      cancel();
    } else if (event.key === 'Tab') {
      event.preventDefault();
      commit(event.shiftKey ? 'left' : 'right');
    }
  };

  const lines = Math.min(MAX_ROWS, Math.max(1, text.split('\n').length));
  return (
    <textarea
      ref={fieldRef}
      aria-label={label}
      value={text}
      rows={lines}
      spellCheck={false}
      onChange={(event) => setText(event.target.value)}
      onKeyDown={handleKeyDown}
      onBlur={() => commit(null, true)}
      className="absolute left-0 top-0 z-[3] block w-[max(100%,160px)] max-w-[480px] resize-none overflow-y-auto rounded-sm border-2 border-accent bg-surface px-2 py-[5px] text-left text-callout font-normal text-ink shadow-popover sheet-figures focus-visible:outline-none"
    />
  );
}
