import { useId } from 'react';
import type { ReactNode } from 'react';

interface InspectorSectionProps {
  title: string;
  children: ReactNode;
}

/** A titled block of the issue inspector, separated from the previous one by a hairline. */
export function InspectorSection({ title, children }: InspectorSectionProps) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="border-t border-hairline pt-4 first:border-t-0 first:pt-0">
      <h3 id={headingId} className="mb-2 text-callout font-semibold text-ink">
        {title}
      </h3>
      {children}
    </section>
  );
}
