import { Skeleton } from '../../components/Skeleton.tsx';

/** The account while it loads, in its layout: the box with the avatar, name and actions, then the role and the details. */
export function UserPlaceholder({ label }: { label: string }) {
  return (
    <div className="flex flex-col gap-5">
      <p role="status" className="sr-only">
        {label}
      </p>
      <div aria-hidden="true" className="rounded-lg border border-hairline bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-b border-hairline p-4">
          <div className="flex items-center gap-4">
            <Skeleton className="size-12 rounded-full" />
            <div className="flex flex-col gap-2.5">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-5 w-20" />
            </div>
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-8 w-28" />
            <Skeleton className="h-8 w-28" />
            <Skeleton className="h-8 w-20" />
          </div>
        </div>
        <div className="flex flex-col gap-5 p-4">
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-3 w-12" />
            <Skeleton className="h-8 w-56 max-w-full" />
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-x-6 gap-y-4">
            {Array.from({ length: 8 }, (_, index) => (
              <div key={index} className="flex flex-col gap-2">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-4 w-32" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
