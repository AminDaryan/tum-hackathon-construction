import { X } from 'lucide-react';
import { Dialog as AriaDialog, Heading, Modal, ModalOverlay } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { IconButton } from './IconButton.tsx';
import { t } from '../i18n/messages.ts';
import { useI18n } from '../i18n/useI18n.ts';
import type { ReactNode } from 'react';

interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  dismissable?: boolean;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  role?: 'dialog' | 'alertdialog';
  /** `blur` blurs and darkens the page behind; `dim` is the light scrim */
  backdrop?: 'dim' | 'blur';
  /** the content, or a function of `{ close }` returning it */
  children?: ReactNode | ((dialog: { close: () => void }) => ReactNode);
}

const SIZES = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-5xl' };

/**
 * Modal dialog (React Aria): traps focus, restores it to the opener, closes on Escape and, when
 * `dismissable`, on a click outside. Controlled through `open` and `onOpenChange`. `children` may
 * be a render function receiving `close`. The backdrop fades in and out and the panel grows in and
 * shrinks out. `backdrop="blur"` blurs and darkens the page behind it, for an overlay that stands
 * in for a page (Settings, Profile).
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  dismissable = true,
  size = 'md',
  role = 'dialog',
  backdrop = 'dim',
  children,
}: DialogProps) {
  useI18n();
  const blur = backdrop === 'blur';
  return (
    <ModalOverlay
      isOpen={open}
      onOpenChange={onOpenChange}
      isDismissable={dismissable}
      className={cx(
        'fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4',
        'data-entering:animate-[scrim-in_200ms_var(--ease-standard)] data-exiting:animate-[scrim-out_160ms_var(--ease-standard)_forwards]',
        blur ? 'bg-scrim-strong backdrop-blur-md' : 'bg-scrim backdrop-blur-[1px]',
        size === 'xl' ? 'pt-[8dvh]' : 'pt-[12dvh]',
      )}
    >
      <Modal
        className={cx(
          'w-full rounded-lg border border-hairline bg-surface shadow-overlay outline-none',
          'data-entering:animate-[overlay-panel-in_200ms_var(--ease-standard)] data-exiting:animate-[overlay-panel-out_160ms_var(--ease-standard)_forwards]',
          SIZES[size],
        )}
      >
        <AriaDialog role={role} className="outline-none">
          {({ close }) => (
            <>
              <div className="flex items-start gap-3 border-b border-hairline py-3 pl-5 pr-2">
                <div className="min-w-0 flex-1 pt-2">
                  <Heading slot="title" className="text-headline text-ink">
                    {title}
                  </Heading>
                  {description && <p className="mt-1 text-callout text-ink-secondary">{description}</p>}
                </div>
                {dismissable && <IconButton icon={X} label={t('Close')} onPress={close} />}
              </div>
              <div className="px-5 py-4">{typeof children === 'function' ? children({ close }) : children}</div>
            </>
          )}
        </AriaDialog>
      </Modal>
    </ModalOverlay>
  );
}
