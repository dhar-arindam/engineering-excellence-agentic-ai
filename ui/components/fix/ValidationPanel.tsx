'use client';

import { useState } from 'react';
import { CheckCircle2, XCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ValidationReport } from '@/types';

interface Props {
  report: ValidationReport;
}

interface CheckRow {
  label: string;
  passed: boolean;
}

export function ValidationPanel({ report }: Props) {
  const [errorsOpen, setErrorsOpen] = useState(false);

  const checks: CheckRow[] = [
    { label: 'Lint',       passed: report.lint_passed },
    { label: 'Tests',      passed: report.tests_passed },
    { label: 'Type Check', passed: report.type_check_passed },
  ];

  const allPassed = checks.every(c => c.passed);

  return (
    <div className={cn(
      'rounded-xl border overflow-hidden',
      allPassed
        ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30'
        : 'border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30',
    )}>
      {/* Title row */}
      <div className="flex items-center justify-between px-4 py-3">
        <p className={cn(
          'text-sm font-semibold',
          allPassed
            ? 'text-emerald-800 dark:text-emerald-200'
            : 'text-amber-800 dark:text-amber-200',
        )}>
          Validation Report
        </p>
        <span className={cn(
          'inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full',
          allPassed
            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300'
            : 'bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300',
        )}>
          {allPassed ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
          {allPassed ? 'All Passed' : 'Issues Found'}
        </span>
      </div>

      {/* Check table */}
      <table className="w-full border-t border-inherit">
        <thead>
          <tr className="text-[10px] uppercase tracking-widest text-slate-400">
            <th className="px-4 py-1.5 text-left font-semibold">Check</th>
            <th className="px-4 py-1.5 text-right font-semibold">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-inherit">
          {checks.map(({ label, passed }) => (
            <tr key={label} className="group">
              <td className="px-4 py-2.5 text-sm text-slate-700 dark:text-slate-300 font-medium">
                {label}
              </td>
              <td className="px-4 py-2.5 text-right">
                {passed ? (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Passed
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-red-600 dark:text-red-400">
                    <XCircle className="h-3.5 w-3.5" />
                    Failed
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Error log (if any) */}
      {report.errors.length > 0 && (
        <div className="border-t border-inherit">
          <button
            onClick={() => setErrorsOpen(v => !v)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
          >
            <span>Error log ({report.errors.length})</span>
            {errorsOpen
              ? <ChevronUp className="h-3.5 w-3.5" />
              : <ChevronDown className="h-3.5 w-3.5" />
            }
          </button>

          {errorsOpen && (
            <div className="border-t border-inherit px-4 py-3 animate-fade-in">
              <pre className="text-[11px] leading-relaxed text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-950/60 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap font-mono">
                {report.errors.join('\n')}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
