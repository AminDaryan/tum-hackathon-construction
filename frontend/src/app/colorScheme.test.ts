import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { setColorSchemePreference } from './colorScheme.ts';

describe('colour scheme', () => {
  let icon: HTMLLinkElement;

  beforeEach(() => {
    icon = document.createElement('link');
    icon.rel = 'icon';
    icon.setAttribute('href', '/favicon.svg');
    document.head.append(icon);
  });

  afterEach(() => {
    icon.remove();
    setColorSchemePreference('system');
  });

  it('shows the tab icon in the colours of the scheme the app is in, whatever the system uses', () => {
    setColorSchemePreference('dark');
    expect(document.documentElement.dataset.colorScheme).toBe('dark');
    expect(icon.getAttribute('href')).toBe('/favicon-dark.svg');

    setColorSchemePreference('light');
    expect(document.documentElement.dataset.colorScheme).toBe('light');
    expect(icon.getAttribute('href')).toBe('/favicon.svg');
  });
});
