import { Button as AriaButton, type ButtonProps as AriaButtonProps, type PressEvent } from 'react-aria-components';
import { Link, type LinkProps } from 'react-router-dom';
import { cx } from '../utils/classNames.ts';
import { HIT_TARGET } from './hitTarget.ts';
import { Spinner } from './Spinner.tsx';
import type { ElementType, ReactNode } from 'react';

/*
 * Buttons are React Aria buttons: `onPress` behaves the same for mouse, touch, pen and keyboard
 * (its event's `target` is the button), with `data-pressed` / `data-disabled` / `data-pending`
 * state attributes, and `isPending`, which keeps focus while busy.
 */
const VARIANT_CLASSES = {
  primary: 'bg-accent text-on-accent hover:bg-accent-hover active:bg-accent-pressed data-pressed:bg-accent-pressed shadow-control',
  secondary: 'state-layer border border-hairline-strong bg-surface text-ink shadow-control hover:border-control-border',
  ghost: 'state-layer bg-transparent text-ink-secondary hover:text-ink',
  danger: 'state-layer border border-violation-border bg-surface text-danger hover:bg-danger-bg',
  link: 'bg-transparent px-0! text-accent-strong underline-offset-2 hover:underline justify-start! whitespace-normal! text-left',
};

const SIZE_CLASSES = {
  sm: 'gap-1.5 px-2.5 text-callout',
  md: 'gap-1.5 px-3 text-callout',
  lg: 'gap-2 px-4 text-body',
};

export type ButtonVariant = keyof typeof VARIANT_CLASSES;

export const BUTTON_VARIANTS = Object.freeze(Object.keys(VARIANT_CLASSES) as ButtonVariant[]);

/**
 * Class names shared by {@link Button} and {@link ButtonLink}.
 */
export function buttonClassName({
  variant = 'secondary',
  size = 'md',
  className,
}: {
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
} = {}): string {
  return cx(
    'inline-flex shrink-0 cursor-pointer select-none items-center justify-center whitespace-nowrap rounded-md font-medium',
    'transition-colors data-disabled:cursor-not-allowed data-disabled:opacity-50 data-pending:cursor-progress',
    HIT_TARGET,
    VARIANT_CLASSES[variant],
    SIZE_CLASSES[size],
    className,
  );
}

interface ButtonContentProps {
  icon?: ElementType;
  iconPosition: 'start' | 'end';
  loading: boolean;
  pendingLabel?: ReactNode;
  children: ReactNode;
}

/**
 * The icon and the label. Every label the button can show (`children`, `pendingLabel`) is laid
 * in the same grid cell, the ones not shown invisible, so the button is
 * always as wide as its widest label and never changes size when its text changes. While
 * loading, a spinner replaces the icon; without an icon (and without a pending label) it sits
 * over the label, which turns transparent but keeps its width and the button's name.
 */
function ButtonContent({ icon: Icon, iconPosition, loading, pendingLabel, children }: ButtonContentProps) {
  const showPending = loading && pendingLabel !== undefined;
  const overlay = loading && !Icon && !showPending;
  let iconNode = null;
  if (loading && Icon) {
    iconNode = <Spinner size="sm" />;
  } else if (Icon) {
    iconNode = <Icon aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />;
  }
  const labels = [
    { key: 'label', node: children, shown: !showPending },
    ...(pendingLabel === undefined ? [] : [{ key: 'pending', node: pendingLabel, shown: showPending }]),
  ];
  if (labels.length === 1 && !overlay) {
    return (
      <>
        {iconPosition === 'start' && iconNode}
        <span>{children}</span>
        {iconPosition === 'end' && iconNode}
      </>
    );
  }
  return (
    <>
      {iconPosition === 'start' && iconNode}
      <span className="relative inline-grid justify-items-center">
        {labels.map(({ key, node, shown }) => (
          <span
            key={key}
            aria-hidden={shown ? undefined : true}
            className={cx('col-start-1 row-start-1', !shown && 'invisible', shown && overlay && 'text-transparent')}
          >
            {node}
          </span>
        ))}
        {overlay && (
          <span className="absolute inset-0 flex items-center justify-center">
            <Spinner size="sm" />
          </span>
        )}
      </span>
      {iconPosition === 'end' && iconNode}
    </>
  );
}

interface ButtonProps extends Omit<AriaButtonProps, 'className' | 'children'> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
  icon?: ElementType;
  iconPosition?: 'start' | 'end';
  loading?: boolean;
  /** the label while `loading` ("Validating…"); its width is reserved, so the button keeps its size */
  pendingLabel?: ReactNode;
  isDisabled?: boolean;
  type?: 'button' | 'submit' | 'reset';
  className?: string;
  onPress?: (event: PressEvent) => void;
  children: ReactNode;
}

/**
 * Push button. Primary (accent) for the main action of a view, secondary for everything else,
 * ghost for low-emphasis actions, danger for destructive ones. Sizes: sm and md (13 px text) and
 * lg (14 px text, for primary page actions); all are at least 32 × 32 px, 48 × 48 on coarse
 * pointers.
 *
 * While `loading`, the button shows a spinner (and `pendingLabel`, if given), is marked busy and
 * ignores presses but keeps focus (it is not disabled), so keyboard users do not lose their place.
 * It keeps its size whatever it shows.
 */
export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  iconPosition = 'start',
  loading = false,
  pendingLabel,
  type = 'button',
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <AriaButton
      type={type}
      className={buttonClassName({ variant, size, className })}
      isPending={loading}
      {...rest}
    >
      <ButtonContent icon={icon} iconPosition={iconPosition} loading={loading} pendingLabel={pendingLabel}>
        {children}
      </ButtonContent>
    </AriaButton>
  );
}

interface ButtonLinkProps extends Omit<LinkProps, 'className' | 'children'> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
  icon?: ElementType;
  iconPosition?: 'start' | 'end';
  className?: string;
  children: ReactNode;
}

/** A router link styled as a button, for navigation actions ("Open workspace"). */
export function ButtonLink({
  to,
  variant = 'secondary',
  size = 'md',
  icon,
  iconPosition = 'start',
  className,
  children,
  ...rest
}: ButtonLinkProps) {
  return (
    <Link to={to} data-button="" className={buttonClassName({ variant, size, className })} {...rest}>
      <ButtonContent icon={icon} iconPosition={iconPosition} loading={false}>
        {children}
      </ButtonContent>
    </Link>
  );
}
