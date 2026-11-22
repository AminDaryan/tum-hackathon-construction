import { cx } from '../../utils/classNames.ts';
import { ROLE_STYLE, initials } from './roles.ts';

const SIZES = {
  sm: 'size-8 text-caption',
  lg: 'size-12 text-callout',
};

interface AvatarProps {
  name?: string;
  role?: string;
  size?: 'sm' | 'lg';
  className?: string;
}

/** The initials of a name on the colour of the role; decorative (the name is said beside it). */
export function Avatar({ name, role, size = 'sm', className }: AvatarProps) {
  const style = ROLE_STYLE[role ?? 'viewer'] ?? ROLE_STYLE.viewer;
  return (
    <span
      aria-hidden="true"
      className={cx(
        'inline-flex shrink-0 select-none items-center justify-center rounded-full bg-linear-to-br font-semibold tracking-wide text-on-accent ring-2 ring-surface',
        style.avatar,
        SIZES[size],
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}
