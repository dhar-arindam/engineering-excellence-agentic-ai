import type { ComponentType } from 'react';

interface EmptyStateProps {
  icon: ComponentType<{ className?: string }>;
  title: string;
  description?: string;
}

export function EmptyState({ icon: Icon, title, description }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 dark:bg-slate-800">
        <Icon className="h-6 w-6 text-slate-400" />
      </div>
      <div>
        <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{title}</p>
        {description && (
          <p className="text-xs text-slate-400 mt-1 max-w-xs">{description}</p>
        )}
      </div>
    </div>
  );
}
