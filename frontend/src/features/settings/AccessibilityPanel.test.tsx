import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  STORAGE_KEY,
  normalize,
  prefersReducedMotion,
  resetAccessibilityPreferences,
  startAccessibility,
} from '../../app/accessibility.ts';
import { mockFetch } from '../../test/fetchMock.ts';
import { renderApp } from '../../test/render.tsx';

const root = () => document.documentElement.dataset;
const stored = () => JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? 'null');

beforeEach(() => {
  resetAccessibilityPreferences();
});

describe('accessibility preferences', () => {
  it('keeps only known values', () => {
    expect(
      normalize({ textSize: 'huge', contrast: 'high', motion: 7, underlineLinks: 'yes', strongFocus: true }),
    ).toEqual({
      textSize: 'default',
      contrast: 'high',
      motion: 'system',
      underlineLinks: false,
      readableText: false,
      strongFocus: true,
    });
    expect(normalize(null).textSize).toBe('default');
  });

  it('applies the saved preferences when the application starts', () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ textSize: 'larger', motion: 'reduce', readableText: true }));
    startAccessibility();
    expect(root().textSize).toBe('larger');
    expect(root().motion).toBe('reduce');
    expect(root().readableText).toBe('true');
    expect(root().contrast).toBe('standard');
    expect(prefersReducedMotion()).toBe(true);
  });

  it('ignores a broken saved value', () => {
    window.localStorage.setItem(STORAGE_KEY, '{not json');
    startAccessibility();
    expect(root().textSize).toBe('default');
    expect(root().strongFocus).toBe('false');
  });
});

describe('Settings, Accessibility', () => {
  it('changes text size, contrast, motion and the reading aids at once, and resets them', async () => {
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    const { user } = renderApp('/settings?tab=accessibility');

    expect(await screen.findByRole('tab', { name: 'Accessibility', selected: true })).toBeInTheDocument();
    const reset = screen.getByRole('button', { name: 'Reset to defaults' });
    expect(reset).toBeDisabled();
    // No sample box: its Approve button and link did nothing.
    expect(screen.queryByRole('group', { name: 'Preview' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();

    const textSize = screen.getByRole('radiogroup', { name: 'Text size' });
    expect(textSize).toHaveAccessibleDescription('Everything grows with the text, the layout included.');
    expect(within(textSize).getByRole('radio', { name: 'Default' })).toBeChecked();
    await user.click(within(textSize).getByRole('radio', { name: 'Larger' }));
    expect(root().textSize).toBe('larger');

    await user.click(within(screen.getByRole('radiogroup', { name: 'Contrast' })).getByRole('radio', { name: 'High' }));
    expect(root().contrast).toBe('high');

    const motion = screen.getByRole('radiogroup', { name: 'Motion' });
    expect(within(motion).getByRole('radio', { name: 'Follow system' })).toBeChecked();
    await user.click(within(motion).getByRole('radio', { name: 'Reduce motion' }));
    expect(root().motion).toBe('reduce');
    expect(prefersReducedMotion()).toBe(true);

    for (const name of ['Underline links', 'Easier reading spacing', 'Strong focus ring']) {
      const toggle = screen.getByRole('switch', { name });
      expect(toggle).not.toBeChecked();
      await user.click(toggle);
      expect(toggle).toBeChecked();
    }
    expect(root().underlineLinks).toBe('true');
    expect(root().readableText).toBe('true');
    expect(root().strongFocus).toBe('true');
    expect(stored()).toEqual({
      textSize: 'larger',
      contrast: 'high',
      motion: 'reduce',
      underlineLinks: true,
      readableText: true,
      strongFocus: true,
    });

    await user.click(reset);
    expect(root().textSize).toBe('default');
    expect(root().underlineLinks).toBe('false');
    expect(stored()).toBeNull();
    expect(within(textSize).getByRole('radio', { name: 'Default' })).toBeChecked();
    expect(screen.getByRole('switch', { name: 'Strong focus ring' })).not.toBeChecked();
  });

  it('is in German when the interface is', async () => {
    window.localStorage.setItem('twb.language', 'de');
    mockFetch([{ path: '/api/v1/projects', respond: [] }]);
    renderApp('/settings?tab=accessibility');
    expect(await screen.findByRole('tab', { name: 'Barrierefreiheit', selected: true })).toBeInTheDocument();
    expect(screen.getByRole('radiogroup', { name: 'Textgröße' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Links unterstreichen' })).toBeInTheDocument();
  });
});
