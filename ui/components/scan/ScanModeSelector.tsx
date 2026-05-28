'use client';

import { Search, Wrench, GitPullRequest, Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ScanOperationMode } from '@/types/scan';

interface ModeOption {
  value: ScanOperationMode;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  desc: string;
  tooltip: string;
  accent: string;
  activeClasses: string;
}

const OPERATION_MODES: ModeOption[] = [
  {
    value: 'analyze',
    icon: Search,
    label: 'Analyze Only',
    desc: 'Read-only scan',
    tooltip: 'Runs all agents and reports findings. No code is modified at any point. Guaranteed read-only.',
    accent: 'text-[#ED1D24] dark:text-red-400',
    activeClasses: 'border-[#ED1D24] bg-red-50 dark:bg-red-950/30 dark:border-red-600',
  },
  {
    value: 'suggest',
    icon: Wrench,
    label: 'Suggest Fix',
    desc: 'Preview patch only',
    tooltip: 'Generates a suggested code patch you can review in the diff viewer. No PR is created and no files are written to the repository.',
    accent: 'text-amber-600 dark:text-amber-400',
    activeClasses: 'border-amber-500 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-600',
  },
  {
    value: 'auto-fix',
    icon: GitPullRequest,
    label: 'Safe Auto-Fix',
    desc: 'Validate + create PR',
    tooltip: 'Applies the patch in an isolated workspace, runs lint/tests/type-check, then opens a pull request only if all checks pass and no breaking changes are detected.',
    accent: 'text-emerald-600 dark:text-emerald-400',
    activeClasses: 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30 dark:border-emerald-600',
  },
];

interface Props {
  value: ScanOperationMode;
  onChange: (mode: ScanOperationMode) => void;
}

export function ScanModeSelector({ value, onChange }: Props) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-2">
        Operation Mode
      </p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {OPERATION_MODES.map(({ value: modeVal, icon: Icon, label, desc, tooltip, accent, activeClasses }) => {
          const active = value === modeVal;
          return (
            <div key={modeVal} className="relative group">
              <button
                type="button"
                onClick={() => onChange(modeVal)}
                className={cn(
                  'w-full flex items-start gap-2.5 rounded-xl p-3 border text-left transition-all duration-200',
                  active
                    ? activeClasses
                    : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 bg-white dark:bg-slate-900',
                )}
              >
                <Icon
                  className={cn('h-4 w-4 mt-0.5 shrink-0', active ? accent : 'text-slate-400')}
                />
                <div className="min-w-0">
                  <p className={cn('text-xs font-semibold', active ? accent : 'text-slate-700 dark:text-slate-300')}>
                    {label}
                  </p>
                  <p className="text-[11px] text-slate-400 truncate">{desc}</p>
                </div>
                <Info className="h-3 w-3 text-slate-300 dark:text-slate-600 shrink-0 mt-0.5 ml-auto" />
              </button>

              {/* Tooltip */}
              <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 z-50 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                <div className="bg-slate-900 dark:bg-slate-700 text-slate-100 text-[11px] leading-relaxed rounded-lg px-3 py-2 shadow-xl border border-slate-700 dark:border-slate-600">
                  {tooltip}
                </div>
                <div className="w-2 h-2 bg-slate-900 dark:bg-slate-700 rotate-45 mx-auto -mt-1 border-r border-b border-slate-700 dark:border-slate-600" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
