import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { PanelDivider } from './PanelDivider.tsx';
import { maxPanelWidth, PANEL_MAX, PANEL_MIN, PANEL_WIDTH_KEY, panelWidthFor } from './usePanelWidth.ts';

function Harness() {
  const [width, setWidth] = useState(600);
  return (
    <PanelDivider
      width={width}
      min={PANEL_MIN}
      max={800}
      onChange={(next: number) => setWidth(Math.min(Math.max(next, PANEL_MIN), 800))}
      onReset={() => setWidth(600)}
      controls="panel"
    />
  );
}

describe('PanelDivider', () => {
  afterEach(() => window.localStorage.clear());

  it('is a focusable vertical separator whose value is the panel width', () => {
    render(<Harness />);
    const divider = screen.getByRole('separator', { name: 'Width of the side panel' });
    expect(divider).toHaveAttribute('aria-orientation', 'vertical');
    expect(divider).toHaveAttribute('aria-valuenow', '600');
    expect(divider).toHaveAttribute('aria-valuemin', String(PANEL_MIN));
    expect(divider).toHaveAttribute('aria-valuemax', '800');
    expect(divider).toHaveAttribute('aria-controls', 'panel');
    expect(divider).toHaveAttribute('tabindex', '0');
  });

  it('moves with the arrow keys (Shift for three steps), Home and End, and resets on double click', () => {
    render(<Harness />);
    const divider = screen.getByRole('separator');
    fireEvent.keyDown(divider, { key: 'ArrowLeft' });
    expect(divider).toHaveAttribute('aria-valuenow', '632');
    fireEvent.keyDown(divider, { key: 'ArrowRight', shiftKey: true });
    expect(divider).toHaveAttribute('aria-valuenow', '536');
    fireEvent.keyDown(divider, { key: 'End' });
    expect(divider).toHaveAttribute('aria-valuenow', '800');
    fireEvent.keyDown(divider, { key: 'Home' });
    expect(divider).toHaveAttribute('aria-valuenow', String(PANEL_MIN));
    fireEvent.doubleClick(divider);
    expect(divider).toHaveAttribute('aria-valuenow', '600');
  });

  it('keeps the panel within its limits and leaves the sheet its minimum width', () => {
    expect(maxPanelWidth(null)).toBe(PANEL_MAX);
    expect(maxPanelWidth(1200)).toBe(1200 - 480 - 48);
    expect(maxPanelWidth(900)).toBe(PANEL_MIN);
    expect(panelWidthFor(null, 1600)).toBe(Math.round(1600 * 0.44));
    expect(panelWidthFor(2000, 1600)).toBe(PANEL_MAX);
    expect(panelWidthFor(100, 1600)).toBe(PANEL_MIN);
    expect(PANEL_WIDTH_KEY).toBe('twb.workspace.panelWidth');
  });
});
