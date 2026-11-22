import { Check, Copy } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Button } from './Button.tsx';
import { IconButton } from './IconButton.tsx';
import { t } from '../i18n/messages.ts';

const SHOWN_MS = 2000;

interface CopyButtonProps {
  text: string;
  label: string;
  variant?: 'primary' | 'secondary' | 'ghost';
  className?: string;
  /** Called once the text is on the clipboard. */
  onCopied?: () => void;
  /** Only the icon, with `label` as its accessible name and tooltip. */
  iconOnly?: boolean;
}

/**
 * Copies a text to the clipboard and says so for two seconds ("Copied"). When the browser
 * refuses (no clipboard access), it says that instead.
 */
export function CopyButton({ text, label, variant = 'ghost', className, onCopied, iconOnly = false }: CopyButtonProps) {
  const [state, setState] = useState('idle');

  useEffect(() => {
    if (state === 'idle') return undefined;
    const timer = setTimeout(() => setState('idle'), SHOWN_MS);
    return () => clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('no clipboard');
      await navigator.clipboard.writeText(text);
      setState('copied');
      onCopied?.();
    } catch {
      setState('failed');
    }
  };

  return (
    <span className="inline-flex items-center gap-2">
      {iconOnly ? (
        <IconButton
          icon={state === 'copied' ? Check : Copy}
          label={state === 'copied' ? t('Copied') : state === 'failed' ? t('The browser did not allow copying.') : label}
          onPress={copy}
          className={className}
        />
      ) : (
        <Button variant={variant} icon={state === 'copied' ? Check : Copy} onPress={copy} className={className}>
          {label}
        </Button>
      )}
      <span role="status" className={iconOnly ? 'sr-only' : 'text-caption text-ink-secondary'}>
        {state === 'copied' ? t('Copied') : state === 'failed' ? t('The browser did not allow copying.') : ''}
      </span>
    </span>
  );
}
