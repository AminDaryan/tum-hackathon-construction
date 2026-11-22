import { Skeleton } from '../../components/Skeleton.tsx';
import { t } from '../../i18n/messages.ts';

/** The heights of the form's fields: name, description, assigned users. */
const FIELD_HEIGHTS = ['h-8', 'h-16', 'h-8'];

/** The form while the project loads, in its layout: the details box with its fields, then the buttons. */
export function EditProjectPlaceholder() {
  return (
    <div className="flex flex-col gap-6">
      <p role="status" className="sr-only">
        {t('Loading the project…')}
      </p>
      <div aria-hidden="true" className="flex flex-col gap-5 rounded-lg border border-hairline bg-surface p-5">
        <Skeleton className="h-5 w-16" />
        {FIELD_HEIGHTS.map((height, index) => (
          <div key={index} className="flex flex-col gap-1.5">
            <Skeleton className="h-3 w-28" />
            <Skeleton className={`w-full ${height}`} />
          </div>
        ))}
      </div>
      <div aria-hidden="true" className="flex justify-end gap-3">
        <Skeleton className="h-8 w-20" />
        <Skeleton className="h-10 w-36" />
      </div>
    </div>
  );
}
