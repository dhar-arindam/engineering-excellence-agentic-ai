'use client';

import { use, useState } from 'react';
import { Loader2, AlertCircle, ArrowLeft, Play, Upload, AlertTriangle, TrendingUp } from 'lucide-react';
import Link from 'next/link';
import { Header } from '@/components/layout/Header';
import { RepoSummary } from '@/components/dashboard/RepoSummary';
import { AgentScoreCards } from '@/components/dashboard/AgentScoreCards';
import { TrendChart } from '@/components/dashboard/TrendChart';
import { AgentBarChart } from '@/components/dashboard/AgentBarChart';
import { ScanHistory } from '@/components/dashboard/ScanHistory';
import { ScoreTrendChart } from '@/components/trends/ScoreTrendChart';
import { RadarTrendChart } from '@/components/trends/RadarTrendChart';
import { useRepository } from '@/hooks/useRepository';
import { useRepositoryTrends } from '@/hooks/useRepositoryTrends';
import { Button } from '@/components/ui/button';
import { useScanModal } from '@/components/providers';

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function RepositoryDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const { data: repo, isLoading, isError, error } = useRepository(id);
  const { data: trends, isLoading: trendsLoading } = useRepositoryTrends(id, { days: 90 });
  const { openTriggerWithPreset } = useScanModal();
  const [showTrends, setShowTrends] = useState(false);

  if (isLoading) {
    return (
      <>
        <Header title="Repository" breadcrumbs={[{ label: 'Repositories', href: '/repositories' }, { label: '...' }]} />
        <main className="flex-1 flex items-center justify-center p-6">
          <div className="flex items-center gap-2 text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm">Loading repository...</span>
          </div>
        </main>
      </>
    );
  }

  if (isError || !repo) {
    return (
      <>
        <Header title="Repository" breadcrumbs={[{ label: 'Repositories', href: '/repositories' }, { label: 'Error' }]} />
        <main className="flex-1 flex flex-col items-center justify-center p-6 gap-4">
          <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 text-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error?.message ?? 'Repository not found'}
          </div>
          <Link href="/repositories">
            <Button variant="outline" size="sm">
              <ArrowLeft className="h-3.5 w-3.5 mr-1.5" />
              Back to Repositories
            </Button>
          </Link>
        </main>
      </>
    );
  }

  const handleRunScan = () => {
    if (repo.source_type === 'github' && repo.repository_url) {
      openTriggerWithPreset({ sourceType: 'github', url: repo.repository_url, name: repo.name });
    } else {
      openTriggerWithPreset({ sourceType: 'local', name: repo.name });
    }
  };

  const trendWarning = trends?.aggregated_trend?.trend_warning;
  const timeSeries = trends?.time_series ?? [];
  const aggConf = trends?.aggregated_trend?.confidence;
  const aggScore = trends?.aggregated_trend?.overall_score;

  return (
    <>
      <Header
        title={repo.name}
        breadcrumbs={[
          { label: 'Repositories', href: '/repositories' },
          { label: repo.name },
        ]}
      />
      <main className="flex-1 p-6 space-y-6">
        {/* Scan action bar */}
        <div className="flex items-center justify-end gap-2">
          {repo.source_type === 'github' ? (
            <Button size="sm" onClick={handleRunScan} className="flex items-center gap-1.5">
              <Play className="h-3.5 w-3.5" />
              Run Scan
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={handleRunScan} className="flex items-center gap-1.5">
              <Upload className="h-3.5 w-3.5" />
              Upload &amp; Scan
            </Button>
          )}
        </div>

        <RepoSummary repo={repo} />

        <section>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">Agent Scores</h2>
          <AgentScoreCards agents={repo.agents} />
        </section>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <TrendChart data={repo.trend} currentScore={repo.overall_score} />
          <AgentBarChart agents={repo.agents} />
        </section>

        {/* Historical Trends section (collapsible) */}
        <section>
          <button
            onClick={() => setShowTrends((v) => !v)}
            className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
          >
            <TrendingUp className="h-3.5 w-3.5" />
            Historical Trends (90 days)
            <span className="text-slate-300 dark:text-slate-600 font-normal normal-case tracking-normal">
              {showTrends ? '▲' : '▼'}
            </span>
          </button>

          {showTrends && (
            <div className="space-y-4">
              {/* Low-confidence trend warning */}
              {trendWarning && (
                <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300 text-sm">
                  <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                  <p>⚠️ {trendWarning}</p>
                </div>
              )}

              {/* Aggregated stats */}
              {!trendsLoading && trends && timeSeries.length > 0 && (
                <div className="flex items-center gap-6 px-4 py-3 rounded-xl bg-slate-50 dark:bg-slate-800/40 text-sm">
                  <div>
                    <span className="text-xs text-slate-400 block">Weighted Avg Score</span>
                    <span className="font-bold text-slate-700 dark:text-slate-200">
                      {aggScore?.toFixed(1)}/100
                    </span>
                  </div>
                  <div>
                    <span className="text-xs text-slate-400 block">Avg Effective Confidence</span>
                    <span className={`font-bold ${
                      (aggConf ?? 0) >= 0.7
                        ? 'text-emerald-600'
                        : (aggConf ?? 0) >= 0.5
                        ? 'text-amber-600'
                        : 'text-red-600'
                    }`}>
                      {Math.round((aggConf ?? 0) * 100)}%
                    </span>
                  </div>
                  <div>
                    <span className="text-xs text-slate-400 block">Scans in Window</span>
                    <span className="font-bold text-slate-700 dark:text-slate-200">{timeSeries.length}</span>
                  </div>
                </div>
              )}

              {trendsLoading ? (
                <div className="flex items-center gap-2 text-slate-400 text-sm py-8 justify-center">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading trend data...
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <ScoreTrendChart data={timeSeries} />
                  <RadarTrendChart data={timeSeries} />
                </div>
              )}
            </div>
          )}
        </section>

        <section>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3">Scan History</h2>
          <ScanHistory scans={repo.scans} />
        </section>
      </main>
    </>
  );
}
