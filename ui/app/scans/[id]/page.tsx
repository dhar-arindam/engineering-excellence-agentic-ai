'use client';

import { use } from 'react';
import { Loader2, AlertCircle, ArrowLeft, GitCommit, Clock, GitBranch, AlertTriangle, RotateCcw } from 'lucide-react';
import Link from 'next/link';
import { Header } from '@/components/layout/Header';
import { AgentScoreCards } from '@/components/dashboard/AgentScoreCards';
import { DriftPanel } from '@/components/dashboard/DriftPanel';
import { IssuesTable } from '@/components/dashboard/IssuesTable';
import { ScanActionsPanel } from '@/components/fix/ScanActionsPanel';
import { ScanRadarChart } from '@/components/scan/ScanRadarChart';
import { AgentConfidencePanel } from '@/components/scan/AgentConfidencePanel';
import { TopRisksPanel } from '@/components/scan/TopRisksPanel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useScan } from '@/hooks/useScan';
import { useScanModal } from '@/components/providers';
import { getScoreColor, formatDate } from '@/lib/utils';

interface PageProps {
  params: Promise<{ id: string }>;
}

const riskVariant: Record<string, 'low' | 'medium' | 'high' | 'critical'> = {
  Low: 'low', Medium: 'medium', High: 'high', Critical: 'critical',
};

function ConfidenceIndicator({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const isHigh   = value >= 0.7;
  const isMedium = value >= 0.5;
  const colorClass = isHigh
    ? 'text-emerald-600 dark:text-emerald-400'
    : isMedium
    ? 'text-amber-600 dark:text-amber-400'
    : 'text-red-600 dark:text-red-400';
  const barColor = isHigh ? 'bg-emerald-500' : isMedium ? 'bg-amber-500' : 'bg-red-500';
  const label    = isHigh ? 'High confidence' : isMedium ? 'Medium confidence' : 'Low confidence';
  return (
    <div className="flex flex-col gap-0.5 mt-1">
      <div className="flex items-center gap-1.5">
        <div className="w-16 h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
          <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
        </div>
        <span className={`text-xs font-semibold ${colorClass}`}>{pct}%</span>
      </div>
      <span className="text-[10px] text-slate-400">{label}</span>
    </div>
  );
}

export default function ScanDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const { data: scan, isLoading, isError, error } = useScan(id);
  const { openTriggerWithPreset } = useScanModal();

  function handleRerun() {
    if (!scan) return;
    openTriggerWithPreset({
      sourceType: scan.source_type === 'local' ? 'local' : 'github',
      url: scan.source_type === 'github' ? scan.repository_url : undefined,
      name: scan.repository_name,
    });
  }

  if (isLoading) {
    return (
      <>
        <Header title="Scan" breadcrumbs={[{ label: 'Scans', href: '/scans' }, { label: '...' }]} />
        <main className="flex-1 flex items-center justify-center p-6">
          <div className="flex items-center gap-2 text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">Loading scan...</span>
          </div>
        </main>
      </>
    );
  }

  if (isError || !scan) {
    return (
      <>
        <Header title="Scan" breadcrumbs={[{ label: 'Scans', href: '/scans' }, { label: 'Error' }]} />
        <main className="flex-1 flex flex-col items-center justify-center p-6 gap-4">
          <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 text-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error?.message ?? 'Scan not found'}
          </div>
          <Link href="/scans">
            <Button variant="outline" size="sm">
              <ArrowLeft className="h-3.5 w-3.5 mr-1.5" />
              Back to Scans
            </Button>
          </Link>
        </main>
      </>
    );
  }

  const overallConf = scan.overall_confidence ?? 0.5;
  const isLowConfidence = overallConf < 0.5;
  const topRisks = scan.top_risks ?? [];
  const radar = scan.radar ?? {};

  return (
    <>
      <Header
        title={`Scan — ${scan.repository_name}`}
        breadcrumbs={[
          { label: 'Scans', href: '/scans' },
          { label: scan.repository_name },
          { label: formatDate(scan.date) },
        ]}
      />
      <main className="flex-1 p-6 space-y-6">

        {/* Low-confidence warning banner */}
        {isLowConfidence && (
          <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 text-sm">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
            <p>
              <strong>Low confidence:</strong> Results may be incomplete due to missing data.
              Confidence: {Math.round(overallConf * 100)}%. Provide more complete repository context
              (test reports, CI config) to improve accuracy.
            </p>
          </div>
        )}

        {/* Scan summary header */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-4 p-5 rounded-2xl border border-slate-100 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
          <div className="flex items-start gap-4 flex-1">
            <div>
              <div className={`text-4xl font-black tracking-tighter ${getScoreColor(scan.overall_score)}`}>
                {scan.overall_score}
                <span className="text-sm font-normal text-slate-400">/100</span>
              </div>
              <ConfidenceIndicator value={overallConf} />
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <Badge variant={riskVariant[scan.risk]}>{scan.risk} Risk</Badge>
                <span className="text-[11px] font-mono bg-slate-100 dark:bg-slate-800 text-slate-500 px-1.5 py-0.5 rounded">
                  {scan.operation_mode}
                </span>
              </div>
              <div className="flex items-center gap-3 text-[11px] text-slate-400 flex-wrap">
                <span className="flex items-center gap-1">
                  <GitBranch className="h-3 w-3" />
                  {scan.branch}
                </span>
                {scan.commit_sha && (
                  <span className="flex items-center gap-1">
                    <GitCommit className="h-3 w-3" />
                    {scan.commit_sha.slice(0, 7)}
                  </span>
                )}
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {scan.duration || formatDate(scan.date)}
                </span>
              </div>
            </div>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 shrink-0">
            <Button variant="outline" size="sm" onClick={handleRerun}>
              <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
              Re-run Scan
            </Button>
            <Link href={`/repositories/${scan.repository_id}`}>
              <Button variant="outline" size="sm">View Repository</Button>
            </Link>
          </div>
        </div>

        {/* Fix / Remediation actions */}
        <ScanActionsPanel scan={scan} />

        {/* Radar chart + Agent confidence breakdown */}
        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <ScanRadarChart radar={radar} />
          <AgentConfidencePanel agents={scan.agents} />
        </section>

        {/* Top risks grouped by severity */}
        {topRisks.length > 0 && (
          <section>
            <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">Top Risks</h2>
            <TopRisksPanel risks={topRisks} />
          </section>
        )}

        {/* Agent score cards (visual summary) */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">Agent Scores</h2>
          <AgentScoreCards agents={scan.agents} />
        </section>

        {/* All issues */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">
            All Issues ({scan.issue_count})
          </h2>
          <IssuesTable issues={scan.issues} />
        </section>

        {/* Drift analysis */}
        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <DriftPanel drift={scan.drift} />
        </section>
      </main>
    </>
  );
}
