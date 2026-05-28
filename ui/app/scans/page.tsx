'use client';

import { useState } from 'react';
import { Loader2, AlertCircle, ScanLine } from 'lucide-react';
import Link from 'next/link';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select } from '@/components/ui/select';
import { Header } from '@/components/layout/Header';
import { useScans } from '@/hooks/useScans';
import { useRepositories } from '@/hooks/useRepositories';
import { formatDate, getScoreColor } from '@/lib/utils';
import type { ScanSummary, ScanStatus } from '@/generated/api-client';

const statusVariant: Record<string, string> = {
  completed: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  failed:    'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  running:   'bg-red-100 text-[#ED1D24] dark:bg-red-900/40 dark:text-red-300',
  queued:    'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
  cancelled: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500',
};

const riskVariant: Record<string, 'low' | 'medium' | 'high' | 'critical'> = {
  Low: 'low', Medium: 'medium', High: 'high', Critical: 'critical',
};

const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '',          label: 'All Statuses' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed',    label: 'Failed' },
  { value: 'running',   label: 'Running' },
  { value: 'queued',    label: 'Queued' },
  { value: 'cancelled', label: 'Cancelled' },
];

export default function ScansPage() {
  const [statusFilter, setStatusFilter] = useState<ScanStatus | ''>('');
  const [repoFilter, setRepoFilter] = useState('');

  const { data, isLoading, isError, error } = useScans({
    limit: 100,
    ...(statusFilter ? { status: statusFilter as ScanStatus } : {}),
    ...(repoFilter ? { repository_id: repoFilter } : {}),
  });
  const { data: reposData } = useRepositories();
  const scans = data?.items ?? [];
  const repos = reposData?.items ?? [];

  return (
    <>
      <Header
        title="Scans"
        breadcrumbs={[{ label: 'Scans' }]}
      />
      <main className="flex-1 p-6 space-y-6">
        {/* Stats + filters bar */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <ScanLine className="h-5 w-5 text-slate-400" />
            <span className="text-sm text-slate-500">
              {isLoading ? '…' : `${data?.total ?? 0} scan${(data?.total ?? 0) !== 1 ? 's' : ''}`}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as ScanStatus | '')}
              className="w-36"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </Select>
            <Select
              value={repoFilter}
              onChange={(e) => setRepoFilter(e.target.value)}
              className="w-44"
            >
              <option value="">All Repositories</option>
              {repos.map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </Select>
            {(statusFilter || repoFilter) && (
              <button
                onClick={() => { setStatusFilter(''); setRepoFilter(''); }}
                className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 underline underline-offset-2"
              >
                Clear filters
              </button>
            )}
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Scans</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {isLoading && (
              <div className="flex items-center justify-center py-16 gap-2 text-sm text-slate-400">
                <Loader2 className="h-5 w-5 animate-spin" />
                Loading scans…
              </div>
            )}
            {isError && (
              <div className="flex items-center gap-2 mx-6 my-4 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 text-sm">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error?.message ?? 'Failed to load scans'}
              </div>
            )}
            {!isLoading && !isError && scans.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 gap-2 text-sm text-slate-400">
                <ScanLine className="h-10 w-10 text-slate-300 dark:text-slate-600" />
                {statusFilter || repoFilter
                  ? <p>No scans match the current filters.</p>
                  : <p>No scans yet. Run a scan from the Repositories page.</p>}
              </div>
            )}
            {!isLoading && !isError && scans.length > 0 && (
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                {scans.map((scan) => <ScanRow key={scan.id} scan={scan} />)}
              </div>
            )}
          </CardContent>
        </Card>
      </main>
    </>
  );
}

function ScanRow({ scan }: { scan: ScanSummary }) {
  return (
    <Link
      href={`/scans/${scan.id}`}
      className="flex items-center gap-4 px-6 py-3.5 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">{scan.repository_name}</span>
          <Badge variant={riskVariant[scan.risk]}>{scan.risk}</Badge>
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${statusVariant[scan.status] ?? ''}`}>
            {scan.status}
          </span>
          <span className="text-[11px] bg-slate-100 dark:bg-slate-800 text-slate-500 px-1.5 py-0.5 rounded font-mono">
            {scan.operation_mode}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-slate-400">
          <span className="font-mono">{scan.branch}</span>
          <span>·</span>
          <span>{formatDate(scan.date)}</span>
          <span>·</span>
          <span>{scan.issue_count} issue{scan.issue_count !== 1 ? 's' : ''}</span>
          <span>·</span>
          <span>{scan.duration}</span>
        </div>
      </div>
      <div className={`text-lg font-bold shrink-0 ${getScoreColor(scan.overall_score)}`}>
        {scan.overall_score}
      </div>
    </Link>
  );
}
