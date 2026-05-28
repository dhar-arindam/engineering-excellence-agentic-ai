import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

interface BadgeProps {
  children: ReactNode;
  variant?: 'default' | 'low' | 'medium' | 'high' | 'critical' | 'info' | 'outline';
  className?: string;
}

const variantClasses: Record<string, string> = {
  default: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  low: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/60 dark:text-emerald-300',
  medium: 'bg-amber-100 text-amber-700 dark:bg-amber-900/60 dark:text-amber-300',
  high: 'bg-red-100 text-red-700 dark:bg-red-900/60 dark:text-red-300',
  critical: 'bg-red-600 text-white dark:bg-red-700',
  info: 'bg-amber-100 text-amber-700 dark:bg-amber-900/60 dark:text-amber-300',
  outline: 'border border-slate-300 text-slate-600 dark:border-slate-600 dark:text-slate-400',
};

export function Badge({ children, variant = 'default', className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium tracking-wide',
        variantClasses[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
