'use client';

import { useState } from 'react';
import { GitPullRequest, ExternalLink, Loader2, CheckCircle2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useCreatePR } from '@/hooks/useCreatePR';
import { Button } from '@/components/ui/button';
import type { BreakingChangeReport, ValidationReport } from '@/types';
import type { ScanOperationMode } from '@/types/scan';

interface Props {
  scanId: string;
  operationMode: ScanOperationMode;
  validationReport?: ValidationReport;
  breakingChangeReport?: BreakingChangeReport;
  /** Pre-existing PR state from the scan record */
  existingPR?: { created: boolean; pr_url?: string };
}

function validationPassed(report?: ValidationReport): boolean {
  if (!report) return false;
  return report.lint_passed && report.tests_passed && report.type_check_passed;
}

function hasBreakingChanges(report?: BreakingChangeReport): boolean {
  return report?.has_breaking_changes === true;
}

export function CreatePRPanel({
  scanId,
  operationMode,
  validationReport,
  breakingChangeReport,
  existingPR,
}: Props) {
  const { mutate: doCreatePR, isPending, data: prResult, error } = useCreatePR(scanId);
  const [localPR, setLocalPR] = useState(existingPR);

  const canCreate =
    operationMode === 'auto-fix' &&
    validationPassed(validationReport) &&
    !hasBreakingChanges(breakingChangeReport);

  const prCreated = localPR?.created || prResult?.created;
  const prUrl = localPR?.pr_url ?? prResult?.pr_url;

  // Compute disabled reason
  let disabledReason: string | null = null;
  if (operationMode !== 'auto-fix') {
    disabledReason = 'Switch to Safe Auto-Fix mode to enable PR creation.';
  } else if (hasBreakingChanges(breakingChangeReport)) {
    disabledReason = 'Breaking changes must be resolved before creating a PR.';
  } else if (!validationPassed(validationReport)) {
    disabledReason = 'All validation checks must pass before creating a PR.';
  }

  return (
    <div className={cn(
      'rounded-xl border p-4 space-y-3',
      prCreated
        ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30'
        : canCreate
          ? 'border-[#ED1D24]/40 bg-red-50 dark:border-red-800 dark:bg-red-950/30'
          : 'border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/40',
    )}>
      <div className="flex items-center gap-2">
        <GitPullRequest className={cn(
          'h-4 w-4',
          prCreated ? 'text-emerald-600 dark:text-emerald-400'
            : canCreate ? 'text-[#ED1D24] dark:text-red-400'
            : 'text-slate-400',
        )} />
        <p className={cn(
          'text-sm font-semibold',
          prCreated ? 'text-emerald-800 dark:text-emerald-200'
            : canCreate ? 'text-[#ED1D24] dark:text-red-200'
            : 'text-slate-600 dark:text-slate-400',
        )}>
          Pull Request
        </p>
      </div>

      {/* PR already created */}
      {prCreated ? (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-sm text-emerald-700 dark:text-emerald-300 font-medium">
            <CheckCircle2 className="h-4 w-4" />
            PR Created Successfully
          </div>
          {prUrl && (
            <a
              href={prUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-[#ED1D24] dark:text-red-400 hover:underline"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              View Pull Request
            </a>
          )}
        </div>
      ) : (
        <>
          {/* Disabled reason */}
          {disabledReason && (
            <p className="text-xs text-slate-500 dark:text-slate-400">{disabledReason}</p>
          )}

          {/* Error */}
          {error && (
            <p className="text-xs text-red-600 dark:text-red-400">
              Failed: {error.message}
            </p>
          )}

          <Button
            size="sm"
            disabled={!canCreate || isPending}
            onClick={() => doCreatePR(undefined, {
              onSuccess: data => setLocalPR({ created: data.created, pr_url: data.pr_url }),
            })}
            className={cn(
              canCreate
                ? 'bg-[#ED1D24] hover:bg-[#C41218] text-white dark:bg-[#ED1D24] dark:hover:bg-[#C41218]'
                : 'opacity-50 cursor-not-allowed',
            )}
          >
            {isPending ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Creating PR…
              </>
            ) : (
              <>
                <GitPullRequest className="h-3.5 w-3.5" />
                Create Safe PR
              </>
            )}
          </Button>
        </>
      )}
    </div>
  );
}
