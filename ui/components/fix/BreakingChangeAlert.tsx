'use client';

import { AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';
import type { BreakingChangeReport } from '@/types';

interface Props {
  report: BreakingChangeReport;
}

export function BreakingChangeAlert({ report }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (!report.has_breaking_changes) return null;

  return (
    <div className="rounded-xl border border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/40 overflow-hidden animate-fade-in">
      {/* Header */}
      <div className="flex items-start gap-3 px-4 py-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/60 mt-0.5">
          <AlertTriangle className="h-4 w-4 text-red-600 dark:text-red-400" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-red-800 dark:text-red-200">
            Breaking Changes Detected
          </p>
          <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">
            PR creation is disabled until these are resolved.
          </p>
        </div>
        {report.details.length > 0 && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="shrink-0 flex items-center gap-1 text-xs font-medium text-red-600 dark:text-red-400 hover:text-red-700 dark:hover:text-red-300 transition-colors"
          >
            {expanded ? 'Hide' : 'Details'}
            {expanded
              ? <ChevronUp className="h-3.5 w-3.5" />
              : <ChevronDown className="h-3.5 w-3.5" />
            }
          </button>
        )}
      </div>

      {/* Detail list */}
      {expanded && report.details.length > 0 && (
        <ul className="border-t border-red-200 dark:border-red-800 px-4 py-3 space-y-1.5 animate-fade-in">
          {report.details.map((detail, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-red-700 dark:text-red-300">
              <span className="mt-0.5 h-1.5 w-1.5 rounded-full bg-red-500 shrink-0" />
              {detail}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
