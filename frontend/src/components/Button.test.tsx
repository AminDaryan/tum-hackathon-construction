import { render, screen } from '@testing-library/react';
import { ShieldCheck } from 'lucide-react';
import { describe, expect, it } from 'vitest';
import { Button } from './Button.tsx';

describe('Button', () => {
  it('keeps every label it can show laid out, so its size does not change, and names itself by the one shown', () => {
    const { rerender } = render(
      <Button icon={ShieldCheck} pendingLabel="Validating…">
        Validate project
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Validate project' });
    // The label shown while it works is already there, invisible, holding its width.
    expect(screen.getByText('Validating…')).toHaveAttribute('aria-hidden', 'true');

    rerender(
      <Button icon={ShieldCheck} loading pendingLabel="Validating…">
        Validate project
      </Button>,
    );
    expect(screen.getByRole('button', { name: 'Validating…' })).toBe(button);
    expect(screen.getByText('Validate project')).toHaveAttribute('aria-hidden', 'true');
  });

  it('keeps the label of a loading button without an icon under the spinner', () => {
    render(<Button loading>Save</Button>);
    expect(screen.getByRole('button', { name: 'Save' })).toHaveTextContent('Save');
  });
});
