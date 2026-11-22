import { Menu as AriaMenu, MenuItem as AriaMenuItem, MenuTrigger, Popover, Separator, type Placement } from 'react-aria-components';
import { cx } from '../utils/classNames.ts';
import { optionClassName, POPOVER } from './Select.tsx';
import type { ElementType, ReactElement } from 'react';

interface MenuProps {
  trigger: ReactElement;
  items: ({
      id?: string;
      label?: string;
      icon?: ElementType;
      danger?: boolean;
      disabled?: boolean;
      separator?: boolean;
      onAction?: () => void;
    })[];
  label: string;
  placement?: Placement;
}

/**
 * Action menu (React Aria): `trigger` is a Button or IconButton; the menu opens on press, Enter,
 * Space or Arrow Down, supports type-ahead and arrow keys, and returns focus to the trigger.
 *
 * `items` is a list of { id, label, icon?, danger?, disabled?, onAction } or { separator: true }.
 */
export function Menu({ trigger, items, label, placement = 'bottom end' }: MenuProps) {
  return (
    <MenuTrigger>
      {trigger}
      <Popover placement={placement} offset={4} className={cx(POPOVER, 'min-w-48')}>
        <AriaMenu aria-label={label} className="outline-none" disabledKeys={items.flatMap((item) => (item.disabled && item.id ? [item.id] : []))}>
          {items.map((item, index) =>
            item.separator ? (
              <Separator key={`separator-${index}`} className="my-1 border-t border-hairline" />
            ) : (
              <AriaMenuItem
                key={item.id}
                id={item.id}
                textValue={item.label}
                onAction={item.onAction}
                className={(state) => cx(optionClassName(state), item.danger && 'text-danger')}
              >
                {item.icon && <item.icon aria-hidden="true" className="size-4 shrink-0 text-ink-tertiary" strokeWidth={1.75} />}
                <span className="min-w-0 flex-1 truncate">{item.label}</span>
              </AriaMenuItem>
            ),
          )}
        </AriaMenu>
      </Popover>
    </MenuTrigger>
  );
}
