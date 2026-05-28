'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  CheckCircle2,
  XCircle,
  X,
  Loader2,
  Wifi,
  WifiOff,
  Copy,
  ChevronsDown,
  RotateCcw,
  ExternalLink,
} from 'lucide-react';
import { useScanStatus } from '@/hooks/useScanStatus';
import { useScanLogs } from '@/hooks/useScanLogs';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { ScanLogEntry, LogLevel } from '@/types/scan';

// ─── Step definitions aligned to progress milestones ─────────────────────────

const STEPS = [
  { label: 'Cloning repository', min: 0, max: 12 },
  { label: 'Parsing structure', min: 12, max: 25 },
  { label: 'Running QA agent', min: 25, max: 42 },
  { label: 'Running Dev agent', min: 42, max: 57 },
  { label: 'Running Architect agent', min: 57, max: 71 },
  { label: 'Running SRE agent', min: 71, max: 84 },
  { label: 'Running Security agent', min: 84, max: 95 },
  { label: 'Generating report', min: 95, max: 100 },
] as const;

// ─── Log styling ──────────────────────────────────────────────────────────────

const LEVEL_STYLES: Record<LogLevel, string> = {
  debug: 'text-slate-500',
  info: 'text-slate-300',
  warn: 'text-yellow-400',
  error: 'text-red-400',
  success: 'text-emerald-400',
};

const LEVEL_BADGE: Record<LogLevel, string> = {
  debug: 'text-slate-600',
  info: 'text-slate-400',
  warn: 'text-yellow-500',
  error: 'text-red-500',
  success: 'text-emerald-500',
};

const AGENT_COLORS: Record<string, string> = {
  QA: 'text-purple-400',
  Dev: 'text-blue-400',
  Architect: 'text-amber-400',
  SRE: 'text-emerald-400',
  Security: 'text-red-400',
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function LogLine({ entry }: { entry: ScanLogEntry }) {
  const time = new Date(entry.timestamp).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  return (
    <div className="flex items-start gap-1.5 py-[2px] font-mono text-[11px] leading-relaxed">
      <span className="text-slate-600 shrink-0 tabular-nums">{time}</span>
      <span className={cn('uppercase shrink-0 w-[14px] font-bold', LEVEL_BADGE[entry.level])}>
        {entry.level[0].toUpperCase()}
      </span>
      {entry.agent && (
        <span className={cn('shrink-0 font-semibold', AGENT_COLORS[entry.agent] ?? 'text-slate-400')}>
          [{entry.agent}]
        </span>
      )}
      <span className={cn('flex-1 break-all', LEVEL_STYLES[entry.level])}>
        {entry.message}
      </span>
    </div>
  );
}

function CircularProgress({ value }: { value: number }) {
  const R = 34;
  const circ = 2 * Math.PI * R;
  const gauge = circ * 0.75;
  const filled = (value / 100) * gauge;
  return (
    <div className="relative h-20 w-20">
      <svg width="80" height="80" className="-rotate-[135deg]">
        {/* Track */}
        <circle
          cx="40" cy="40" r={R}
          fill="none"
          stroke="currentColor"
          strokeWidth="6"
          strokeLinecap="round"
          className="text-slate-200 dark:text-slate-700"
          strokeDasharray={`${gauge} ${circ}`}
        />
        {/* Fill */}
        <circle
          cx="40" cy="40" r={R}
          fill="none"
          stroke="#ED1D24"
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circ}`}
          style={{ transition: 'stroke-dasharray 0.7s cubic-bezier(0.34,1.56,0.64,1)' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-base font-black text-[#ED1D24] tabular-nums">{value}%</span>
      </div>
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

export function ScanProgressDialog({ scanId, repositoryId, onClose, onRetry }: Props) {
  const router = useRouter();
  const [autoScroll, setAutoScroll] = useState(true);
  const [copyState, setCopyState] = useState<'idle' | 'copied'>('idle');
  const logsEndRef = useRef<HTMLDivElement>(null);
  const logsContainerRef = useRef<HTMLDivElement>(null);

  const { data: statusData } = useScanStatus(scanId);
  const status = statusData?.status ?? 'queued';
  const progress = statusData?.progress_percentage ?? 0;
  const isActive = status === 'queued' || status === 'running';

  const { logs, connected, clearLogs } = useScanLogs(scanId, isActive);

  // Auto-navigate 2 s after completion
  useEffect(() => {
    if (status !== 'completed') return;
    const t = setTimeout(() => {
      onClose();
      router.push(`/repo/${repositoryId}/scan/${scanId}`);
    }, 2_000);
    return () => clearTimeout(t);
  }, [status, scanId, repositoryId, router, onClose]);

  // Auto-scroll log pane
  useEffect(() => {
    if (autoScroll) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const handleLogsScroll = () => {
    const el = logsContainerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    setAutoScroll(atBottom);
  };

  const copyLogs = async () => {
    if (logs.length === 0) return;
    const text = logs
      .map(l =>
        [
          new Date(l.timestamp).toISOString(),
          `[${l.level.toUpperCase()}]`,
          l.agent ? `[${l.agent}]` : '',
          l.message,
        ]
          .filter(Boolean)
          .join(' '),
      )
      .join('\n');
    await navigator.clipboard.writeText(text).catch(() => {});
    setCopyState('copied');
    setTimeout(() => setCopyState('idle'), 2_000);
  };

  // Derive display progress: add a tiny offset in queued state so bar is visible
  const displayProgress = status === 'queued' ? Math.max(progress, 4) : progress;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-fade-in" />

      <div className="relative z-10 w-full max-w-2xl bg-white dark:bg-[#1a0505] rounded-2xl shadow-2xl border border-slate-200 dark:border-[#3d0a0a] animate-scale-in flex flex-col max-h-[90vh]">

        {/* ── Animated progress stripe (top) ── */}
        <div className="h-1 rounded-t-2xl overflow-hidden bg-slate-100 dark:bg-slate-800 shrink-0">
          <div
            className={cn(
              'h-full transition-all duration-700 ease-out',
              status === 'completed' ? 'bg-emerald-500' :
              status === 'failed'    ? 'bg-red-500' : 'bg-[#ED1D24]',
            )}
            style={{ width: `${status === 'completed' ? 100 : displayProgress}%` }}
          />
        </div>

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800 shrink-0">
          <div>
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              {status === 'completed' ? 'Scan Complete ✓' :
               status === 'failed'    ? 'Scan Failed' :
               status === 'queued'    ? 'Scan Queued' : 'Scan Running'}
            </h2>
            <p className="text-[11px] text-slate-400 font-mono mt-0.5">{scanId}</p>
          </div>
          {!isActive && (
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* ── Body (scrollable) ── */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="px-6 py-5 space-y-5">

            {/* Status indicator + step list */}
            <div className="flex items-start gap-5">
              {/* Visual indicator */}
              <div className="shrink-0 mt-1">
                {status === 'completed' ? (
                  <CheckCircle2 className="h-16 w-16 text-emerald-500" />
                ) : status === 'failed' ? (
                  <XCircle className="h-16 w-16 text-red-500" />
                ) : status === 'queued' ? (
                  <div className="h-16 w-16 flex items-center justify-center">
                    <Loader2 className="h-10 w-10 text-[#ED1D24] animate-spin" />
                  </div>
                ) : (
                  <CircularProgress value={progress} />
                )}
              </div>

              {/* Text + steps */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-1">
                  {status === 'completed' ? 'All agents completed successfully' :
                   status === 'failed'    ? (statusData?.error_message ?? 'Scan encountered an error') :
                   status === 'queued'    ? 'Your scan is queued and will start shortly…' :
                   (statusData?.current_step ?? `Running analysis — ${progress}%`)}
                </p>
                {status === 'completed' && (
                  <p className="text-xs text-emerald-600 dark:text-emerald-400">
                    Redirecting to results in 2 seconds…
                  </p>
                )}
                {statusData?.estimated_remaining_seconds != null && isActive && (
                  <p className="text-xs text-slate-400 mt-0.5">
                    ~{Math.ceil(statusData.estimated_remaining_seconds / 60)} min remaining
                  </p>
                )}

                {/* Step checklist (running/queued) */}
                {isActive && (
                  <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
                    {STEPS.map(step => {
                      const done = progress > step.max;
                      const active = !done && progress >= step.min;
                      return (
                        <div
                          key={step.label}
                          className={cn(
                            'flex items-center gap-1.5 text-[11px] transition-colors duration-300',
                            done   ? 'text-emerald-500 dark:text-emerald-400' :
                            active ? 'text-[#ED1D24] dark:text-red-400 font-medium' :
                                     'text-slate-300 dark:text-slate-600',
                          )}
                        >
                          {done ? (
                            <CheckCircle2 className="h-3 w-3 shrink-0" />
                          ) : active ? (
                            <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
                          ) : (
                            <div className="h-3 w-3 rounded-full border border-current shrink-0" />
                          )}
                          {step.label}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* ── Live log terminal ── */}
            <div className="rounded-xl overflow-hidden border border-slate-800 dark:border-slate-700">
              {/* Terminal title bar */}
              <div className="flex items-center justify-between px-3 py-2 bg-[#1a1f2e] border-b border-slate-700/60">
                <div className="flex items-center gap-2">
                  {/* macOS traffic lights */}
                  <div className="flex gap-1.5">
                    <div className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
                    <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/70" />
                    <div className="h-2.5 w-2.5 rounded-full bg-green-500/70" />
                  </div>
                  <span className="text-[11px] text-slate-400 font-mono select-none">
                    logs — {scanId}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {/* Connection badge */}
                  <div className={cn(
                    'flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] transition-colors',
                    connected
                      ? 'bg-emerald-900/50 text-emerald-400'
                      : 'bg-slate-700/60 text-slate-500',
                  )}>
                    {connected
                      ? <Wifi className="h-2.5 w-2.5" />
                      : <WifiOff className="h-2.5 w-2.5" />}
                    {connected ? 'Live' : isActive ? 'Reconnecting…' : 'Ended'}
                  </div>

                  {/* Auto-scroll toggle */}
                  <button
                    onClick={() => setAutoScroll(v => !v)}
                    title="Toggle auto-scroll"
                    className={cn(
                      'flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] transition-colors',
                      autoScroll
                        ? 'bg-red-900/50 text-red-400'
                        : 'bg-slate-700/60 text-slate-500 hover:text-slate-300',
                    )}
                  >
                    <ChevronsDown className="h-2.5 w-2.5" />
                    Scroll
                  </button>

                  {/* Copy */}
                  <button
                    onClick={copyLogs}
                    disabled={logs.length === 0}
                    title="Copy all logs"
                    className={cn(
                      'p-1 rounded transition-colors',
                      copyState === 'copied'
                        ? 'text-emerald-400'
                        : 'text-slate-500 hover:text-slate-300 disabled:opacity-30',
                    )}
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </button>

                  {/* Clear */}
                  <button
                    onClick={clearLogs}
                    disabled={logs.length === 0}
                    title="Clear log pane"
                    className="p-1 rounded text-slate-500 hover:text-slate-300 transition-colors disabled:opacity-30"
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {/* Log output */}
              <div
                ref={logsContainerRef}
                onScroll={handleLogsScroll}
                className="bg-[#0d1117] p-3 h-56 overflow-y-auto"
              >
                {logs.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full gap-2 select-none">
                    {connected ? (
                      <>
                        <Loader2 className="h-5 w-5 text-slate-600 animate-spin" />
                        <p className="text-[11px] text-slate-600 font-mono">Waiting for log stream…</p>
                      </>
                    ) : (
                      <>
                        <WifiOff className="h-5 w-5 text-slate-700" />
                        <p className="text-[11px] text-slate-600 font-mono">
                          {isActive ? 'Connecting to WebSocket…' : 'Log stream closed'}
                        </p>
                      </>
                    )}
                  </div>
                ) : (
                  <>
                    {logs.map(entry => <LogLine key={entry.id} entry={entry} />)}
                    <div ref={logsEndRef} />
                  </>
                )}
              </div>

              {/* Copy confirmation snack */}
              {copyState === 'copied' && (
                <div className="absolute bottom-20 right-6 bg-emerald-600 text-white text-xs font-medium px-3 py-1.5 rounded-lg shadow-lg animate-scale-in pointer-events-none">
                  ✓ Copied to clipboard
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Footer (terminal / completed / failed) ── */}
        {!isActive && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100 dark:border-slate-800 rounded-b-2xl shrink-0">
            {status === 'failed' ? (
              <>
                <p className="text-xs text-red-500 dark:text-red-400 truncate mr-4">
                  {statusData?.error_message ?? 'Scan failed. Check repository access and try again.'}
                </p>
                <div className="flex gap-2 shrink-0">
                  <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
                  <Button size="sm" onClick={onRetry}>
                    <RotateCcw className="h-3.5 w-3.5" />
                    Try Again
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="text-xs text-emerald-600 dark:text-emerald-400">
                  Scan complete — redirecting…
                </p>
                <Button
                  size="sm"
                  onClick={() => { onClose(); router.push(`/repo/${repositoryId}/scan/${scanId}`); }}
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  View Results
                </Button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
