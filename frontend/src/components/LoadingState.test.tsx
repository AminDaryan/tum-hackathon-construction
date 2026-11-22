import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LoadingState } from './LoadingState.tsx';

describe('LoadingState', () => {
  it('draws placeholder shapes, hidden from screen readers, and says what is loading', () => {
    const { container } = render(<LoadingState variant="table" label="Loading projects…" />);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Loading projects…');
    expect(screen.getByText('Loading projects…')).toHaveClass('sr-only');
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(5);
    expect(container.querySelector('[aria-hidden="true"]')).toContainElement(container.querySelector('.animate-pulse'));
    expect(container.querySelector('svg')).toBeNull();
  });

  it('shows the label when it carries information, such as a validation still running', () => {
    render(<LoadingState variant="list" showLabel label="The validation is still running." />);
    expect(screen.getByText('The validation is still running.')).not.toHaveClass('sr-only');
  });

  it.each(['text', 'list', 'table', 'sheet', 'pdf', 'block'] as const)('has a %s shape', (variant) => {
    const { container } = render(<LoadingState variant={variant} label="Loading…" />);
    expect(container.querySelector('.animate-pulse')).not.toBeNull();
  });
});
