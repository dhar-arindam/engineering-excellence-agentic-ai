'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Minus,
  X,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  RotateCcw,
  Terminal,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { useScanStatus } from '@/hooks/useScanStatus';
import { useScanLogs } from '@/hooks/useScanLogs';
import { cn } from '@/lib/utils';
import type { ScanLogEntry, LogLevel } from '@/types/scan';

// ─── Steps aligned to progress checkpoints ───────────────────────────────────

const STEPS = [
  { label: 'Cloning',    agent: null,        min: 0,  max: 12  },
  { label: 'Parsing',    agent: null,        min: 12, max: 25  },
  { label: 'QA',         agent: 'QA',        min: 25, max: 42  },
  { label: 'Dev',        agent: 'Dev',       min: 42, max: 57  },
  { label: 'Architect',  agent: 'Architect', min: 57, max: 71  },
  { label: 'SRE',        agent: 'SRE',       min: 71, max: 84  },
  { label: 'Security',   agent: 'Security',  min: 84, max: 95  },
  { label: 'Report',     agent: null,        min: 95, max: 100 },
] as const;

const AGENT_COLORS: Record<string, string> = {
  QA:        'text-purple-500',
  Dev:       'text-blue-500',
  Architect: 'text-amber-500',
  SRE:       'text-emerald-500',
  Security:  'text-[#ED1D24]',
};

const LEVEL_STYLES: Record<LogLevel, string> = {
  debug:   'text-slate-500',
  info:    'text-slate-300',
  warn:    'text-yellow-400',
  error:   'text-red-400',
  success: 'text-emerald-400',
};

// ─── Log line ─────────────────────────────────────────────────────────────────

function LogLine({ entry }: { entry: ScanLogEntry }) {
  const time = new Date(entry.timestamp).toLocaleTimeString('en-US', {
    hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  return (
    <div className="flex items-start gap-1 py-[1px] font-mono text-[10px] leading-relaxed">
      <span className="text-slate-600 shrink-0 tabular-nums">{time}</span>
      {entry.agent && (
        <span className={cn('shrink-0 font-bold', AGENT_COLORS[entry.agent] ?? 'text-slate-400')}>
          [{entry.agent}]
        </span>
      )}
      <span className={cn('flex-1 break-all', LEVEL_STYLES[entry.level])}>
        {entry.message}
      </span>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface Props {
  scanId: string;
  repositoryId: string;
  onClose: () => void;
  onRetry: () => void;
}

export function ActiveScanBanner({ scanId, repositoryId, onClose, onRetry }: Props) {
  const router = useRouter();
  const [minimized, setMinimized] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const { data: statusData } = useScanStatus(scanId);
  const status = statusData?.status ?? 'queued';
  const progress = statusData?.progress_percentage ?? 0;
  const isActive = status === 'queued' || status === 'running';
  const isCompleted = status === 'completed';
  const isFailed = status === 'failed';

  const { logs, connected } = useScanLogs(scanId, isActive);

  // Auto-scroll logs when open
  useEffect(() => {
    if (logsOpen) logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs, logsOpen]);

  // Auto-navigate 3s after completion
  useEffect(() => {
    if (!isCompleted) return;
    const t = setTimeout(() => {
      onClose();
      router.push(`/scans/${scanId}`);
    }, 3_000);
    return () => clearTimeout(t);
  }, [isCompleted, scanId, router, onClose]);

  const handleCancel = async () => {
    setCancelling(true);
    try {
      const { apiClient } = await import('@/lib/api-client');
      await apiClient.scans.cancel(scanId);
    } catch { /* swallow */ } finally {
      setCancelling(false);
    }
  };

  const handleViewResults = () => {
    onClose();
    router.push(`/scans/${scanId}`);
  };

  // Derive active step label for display
  const activeStep = STEPS.find(s => !( progress > s.max) && progress >= s.min);
  const displayProgress = status === 'queued' ? Math.max(progress, 3) : progress;

  // Header colours by status
  const headerCls = isCompleted
    ? 'bg-emerald-600'
    : isFailed
    ? 'bg-red-700'
    : 'bg-[#ED1D24]';

  // ── Minimised pill ──────────────────────────────────────────────────────────
  if (minimized) {
    return (
      <div className="fixed bottom-5 right-5 z-50">
        <button
          onClick={() => setMinimized(false)}
          className={cn(
            'flex items-center gap-2 px-3 py-2 rounded-full shadow-2xl text-white text-xs font-semibold transition-all hover:scale-105',
            headerCls,
          )}
        >
          {isCompleted ? (
            <CheckCircle2 className="h-3.5 w-3.5" />
          ) : isFailed ? (
            <XCircle className="h-3.5 w-3.5" />
          ) : (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          )}
          {isCompleted ? 'Complete' : isFailed ? 'Failed' : `${progress}%`}
          {isActive && (
            <div className="h-1.5 w-12 bg-white/30 rounded-full overflow-hidden">
              <div
                className="h-full bg-white rounded-full transition-all duration-700"
                style={{ width: `${displayProgress}%` }}
              />
            </div>
          )}
        </button>
      </div>
    );
  }

  // ── Full panel ──────────────────────────────────────────────────────────────
  return (
    <div className="fixed bottom-5 right-5 z-50 w-[360px] rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-[#1a0505] overflow-hidden flex flex-col animate-scale-in">

      {/* Header */}
      <div className={cn('flex items-center justify-between px-4 py-2.5 text-white', headerCls)}>
        <div className="flex items-center gap-2 min-w-0">
          {isCompleted ? (
            <CheckCircle2 className="h-4 w-4 shrink-0" />
          ) : isFailed ? (
            <XCircle className="h-4 w-4 shrink-0" />
          ) : (
            <Loader2 className="h-4 w-4 animate-spin shrink-0" />
          )}
          <span className="text-sm font-semibold truncate">
            {isCompleted ? 'Scan Complete!' : isFailed ? 'Scan Failed' : status === 'queued' ? 'Queued…' : `Scanning — ${progress}%`}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0 ml-2">
          <button
            onClick={() => setMinimized(true)}
            className="p-1 rounded hover:bg-white/20 transition-colors"
            title="Minimise"
          >
            <Minus className="h-3.5 w-3.5" />
          </button>
          {!isActive && (
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-white/20 transition-colors"
              title="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1 bg-slate-100 dark:bg-slate-800 shrink-0">
        <div
          className={cn(
            'h-full transition-all duration-700 ease-out',
            isCompleted ? 'bg-emerald-500' : isFailed ? 'bg-red-500' : 'bg-[#ED1D24]',
          )}
          style={{ width: `${isCompleted ? 100 : displayProgress}%` }}
        />
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-3">

        {/* Current step / status message */}
        <div>
          {isCompleted ? (
            <div>
              <p className="text-sm font-semibold text-emerald-600 dark:text-emerald-400">
                All agents completed successfully ✓
              </p>
              <p className="text-xs text-slate-400 mt-0.5">Redirecting to results in 3 seconds…</p>
            </div>
          ) : isFailed ? (
            <p className="text-sm font-semibold text-red-600 dark:text-red-400">
              {statusData?.error_message ?? 'Scan encountered an error. Check repo access and try again.'}
            </p>
          ) : (
            <div className="flex items-start gap-2">
              <div className="flex-1 min-w-0">
                <p className={cn(
                  'text-sm font-semibold truncate',
                  activeStep?.agent ? (AGENT_COLORS[activeStep.agent] ?? 'text-[#ED1D24]') : 'text-[#ED1D24] dark:text-red-400',
                )}>
                  {statusData?.current_step
                    ? statusData.current_step
                    : activeStep
                    ? activeStep.agent
                      ? `Running ${activeStep.agent} agent`
                      : activeStep.label
                    : status === 'queued'
                    ? 'Waiting to start…'
                    : `Analysing — ${progress}%`}
                </p>
                {statusData?.estimated_remaining_seconds != null && isActive && (
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    ~{Math.ceil(statusData.estimated_remaining_seconds / 60)} min remaining
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Step grid (active / queued only) */}
        {(isActive) && (
          <div className="grid grid-cols-4 gap-1.5">
            {STEPS.map(step => {
              const done   = progress > step.max;
              const active = !done && progress >= step.min;
              return (
                <div
                  key={step.label}
                  className={cn(
                    'flex flex-col items-center gap-0.5 px-1 py-1.5 rounded-lg border text-center transition-all duration-300',
                    done
                      ? 'border-emerald-200 dark:border-emerald-900 bg-emerald-50 dark:bg-emerald-950/30'
                      : active
                      ? 'border-[#ED1D24]/40 bg-red-50 dark:bg-red-950/30'
                      : 'border-slate-100 dark:border-slate-800 bg-transparent',
                  )}
                >
                  {done ? (
                    <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0" />
                  ) : active ? (
                    <Loader2 className="h-3 w-3 text-[#ED1D24] dark:text-red-400 animate-spin shrink-0" />
                  ) : (
                    <div className="h-3 w-3 rounded-full border border-slate-300 dark:border-slate-600 shrink-0" />
                  )}
                  <span className={cn(
                    'text-[9px] font-medium leading-tight',
                    done   ? 'text-emerald-600 dark:text-emerald-400' :
                    active ? 'text-[#ED1D24] dark:text-red-400' :
                             'text-slate-400 dark:text-slate-600',
                  )}>
                    {step.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Logs toggle */}
      <div className="px-4 pb-1">
        <button
          onClick={() => setLogsOpen(v => !v)}
          className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
        >
          <Terminal className="h-3 w-3" />
          Logs
          {logs.length > 0 && (
            <span className="bg-slate-100 dark:bg-slate-800 text-slate-500 rounded-full px-1.5 py-px text-[9px] font-medium">
              {logs.length}
            </span>
          )}
          {connected
            ? <Wifi className="h-2.5 w-2.5 text-emerald-500" />
            : <WifiOff className="h-2.5 w-2.5 text-slate-400" />}
          {logsOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
      </div>

      {/* Log terminal (collapsible) */}
      {logsOpen && (
        <div className="mx-4 mb-3 rounded-xl overflow-hidden border border-slate-700">
          <div className="bg-[#0d1117] p-2.5 h-32 overflow-y-auto">
            {logs.length === 0 ? (
              <p className="text-[10px] text-slate-600 font-mono text-center mt-8">
                {connected ? 'Waiting for log stream…' : 'Connecting…'}
              </p>
            ) : (
              <>
                {logs.slice(-80).map(entry => <LogLine key={entry.id} entry={entry} />)}
                <div ref={logsEndRef} />
              </>
            )}
          </div>
        </div>
      )}

      {/* Footer actions */}
      <div className="flex items-center justify-between gap-2 px-4 pb-3 border-t border-slate-100 dark:border-slate-800 pt-2.5">
        {isActive ? (
          <>
            <button
              onClick={handleCancel}
              disabled={cancelling}
              className="flex items-center gap-1 text-xs text-slate-400 hover:text-red-500 transition-colors disabled:opacity-50"
            >
              {cancelling ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
              Cancel scan
            </button>
            <button
              onClick={handleViewResults}
              className="flex items-center gap-1.5 text-xs font-medium text-[#ED1D24] hover:text-red-700 transition-colors"
            >
              View scan
              <ExternalLink className="h-3 w-3" />
            </button>
          </>
        ) : isFailed ? (
          <>
            <button onClick={onClose} className="text-xs text-slate-400 hover:text-slate-600 transition-colors">
              Dismiss
            </button>
            <button
              onClick={onRetry}
              className="flex items-center gap-1.5 text-xs font-medium text-[#ED1D24] hover:text-red-700 transition-colors"
            >
              <RotateCcw className="h-3 w-3" />
              Try again
            </button>
          </>
        ) : (
          <>
            <p className="text-xs text-emerald-600 dark:text-emerald-400 font-medium">
              Redirecting…
            </p>
            <button
              onClick={handleViewResults}
              className="flex items-center gap-1.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 transition-colors"
            >
              View Results
              <ExternalLink className="h-3 w-3" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
