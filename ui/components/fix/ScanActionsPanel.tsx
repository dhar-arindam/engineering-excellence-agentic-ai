'use client';

import { useState } from 'react';
import {
  Lock, ArrowRight, CheckCircle2, Circle,
  Info, Wand2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { BreakingChangeAlert } from '@/components/fix/BreakingChangeAlert';
import { ValidationPanel } from '@/components/fix/ValidationPanel';
import { CreatePRPanel } from '@/components/fix/CreatePRPanel';
import { PatchPreviewModal } from '@/components/fix/PatchPreviewModal';
import { Button } from '@/components/ui/button';
import type { Scan } from '@/types';

// ─── Execution timeline ───────────────────────────────────────────────────────

type StepStatus = 'done' | 'active' | 'pending';

interface TimelineStep {
  label: string;
  status: StepStatus;
}

function getTimelineSteps(scan: Scan): TimelineStep[] {
  const mode = scan.operation_mode ?? 'analyze';

  const steps: TimelineStep[] = [
    { label: 'Analyze', status: 'done' },
  ];

  if (mode === 'suggest' || mode === 'auto-fix') {
    steps.push({
      label: 'Patch',
      status: scan.patch_available ? 'done' : 'active',
    });
  }

  if (mode === 'auto-fix') {
    steps.push({
      label: 'Validate',
      status: scan.validation_report
        ? 'done'
        : scan.patch_available ? 'active' : 'pending',
    });
    steps.push({
      label: 'PR',
      status: scan.fix_pr?.created
        ? 'done'
        : scan.validation_report ? 'active' : 'pending',
    });
  }

  return steps;
}

const stepColors: Record<StepStatus, string> = {
  done:    'text-emerald-600 dark:text-emerald-400 border-emerald-400 dark:border-emerald-600 bg-emerald-50 dark:bg-emerald-950/30',
  active:  'text-[#ED1D24] dark:text-red-400 border-[#ED1D24]/60 dark:border-red-600 bg-red-50 dark:bg-red-950/30',
  pending: 'text-slate-400 border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800/40',
};

function ExecutionTimeline({ scan }: { scan: Scan }) {
  const steps = getTimelineSteps(scan);
  if (steps.length <= 1) return null;

  return (
    <div className="flex items-center gap-1 flex-wrap">
      {steps.map((step, i) => (
        <div key={step.label} className="flex items-center gap-1">
          <span className={cn(
            'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
            stepColors[step.status],
          )}>
            {step.status === 'done'
              ? <CheckCircle2 className="h-3 w-3 shrink-0" />
              : <Circle       className="h-3 w-3 shrink-0" />}
            {step.label}
          </span>
          {i < steps.length - 1 && (
            <ArrowRight className="h-3 w-3 text-slate-300 dark:text-slate-600 shrink-0" />
          )}
        </div>
      ))}
    </div>
  );
}

// ─── ScanActionsPanel ─────────────────────────────────────────────────────────

interface Props {
  scan: Scan;
}

export function ScanActionsPanel({ scan }: Props) {
  const [patchOpen, setPatchOpen] = useState(false);
  const operationMode = scan.operation_mode ?? 'analyze';

  const hasActions =
    scan.read_only !== undefined ||
    scan.patch_available ||
    scan.validation_report ||
    scan.breaking_change_report ||
    operationMode !== 'analyze';

  if (!hasActions) return null;

  return (
    <section className="space-y-4">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">
        Fix &amp; Remediation
      </h2>

      {/* Read-only badge + timeline */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 flex-wrap">
        {scan.read_only && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300 w-fit">
            <Lock className="h-3 w-3 shrink-0" />
            Read-Only Scan Guaranteed
          </span>
        )}
        <ExecutionTimeline scan={scan} />
      </div>

      {/* Workspace isolation notice */}
      {operationMode !== 'analyze' && (
        <div className="flex items-start gap-2.5 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/20 px-3.5 py-2.5">
          <Info className="h-4 w-4 text-amber-500 dark:text-amber-400 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
            All modifications are performed in an <strong>isolated workspace</strong>.
            The original branch remains completely unchanged.
          </p>
        </div>
      )}

      {/* Breaking change alert */}
      {scan.breaking_change_report && (
        <BreakingChangeAlert report={scan.breaking_change_report} />
      )}

      {/* Validation panel */}
      {scan.validation_report && (
        <ValidationPanel report={scan.validation_report} />
      )}

      {/* Patch preview */}
      {scan.patch_available && (
        <>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPatchOpen(true)}
            className="flex items-center gap-2"
          >
            <Wand2 className="h-3.5 w-3.5" />
            View Suggested Changes
          </Button>

          <PatchPreviewModal
            scanId={scan.id}
            open={patchOpen}
            onClose={() => setPatchOpen(false)}
          />
        </>
      )}

      {/* Create PR */}
      <CreatePRPanel
        scanId={scan.id}
        operationMode={operationMode}
        validationReport={scan.validation_report}
        breakingChangeReport={scan.breaking_change_report}
        existingPR={scan.fix_pr}
      />
    </section>
  );
}
