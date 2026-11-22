import { Skeleton, SkeletonTable } from '../../components/Skeleton.tsx';
import { t } from '../../i18n/messages.ts';

/** The report while it loads, in its layout: the title and Print, the bills, then the positions. */
export function ProjectReportPlaceholder() {
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="sr-only">
        {t('Loading the report…')}
      </p>
      <div aria-hidden="true" className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          <Skeleton className="h-5 w-72 max-w-full" />
          <Skeleton className="h-3 w-56 max-w-full" />
        </div>
        <Skeleton className="h-8 w-44" />
      </div>
      <div aria-hidden="true" className="flex flex-col gap-2.5 rounded-lg border border-hairline bg-surface px-4 py-3">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="h-3 w-80 max-w-full" />
      </div>
      <div aria-hidden="true" className="rounded-lg border border-hairline bg-surface">
        <div className="flex flex-col gap-2 border-b border-hairline px-4 py-3">
          <Skeleton className="h-4 w-64 max-w-full" />
          <Skeleton className="h-3 w-48" />
        </div>
        <SkeletonTable rows={8} columns={4} />
      </div>
    </div>
  );
}
