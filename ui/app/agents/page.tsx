'use client';

import { Cpu, TestTube2, Code2, Building2, Server, ShieldCheck } from 'lucide-react';
import { Loader2, AlertCircle } from 'lucide-react';
import Link from 'next/link';
import { Header } from '@/components/layout/Header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAgentsPerformance } from '@/hooks/useAgentsPerformance';
import { getScoreColor, formatDate } from '@/lib/utils';
import type { AgentType } from '@/generated/api-client';

type AgentMeta = { icon: React.ComponentType<{ className?: string }>; color: string; bg: string; label: string };

const AGENT_META: Record<AgentType, AgentMeta> = {
  QA:        { icon: TestTube2,   color: 'text-purple-600',  bg: 'bg-purple-100 dark:bg-purple-900/40',   label: 'Senior QA' },
  Dev:       { icon: Code2,       color: 'text-blue-600',    bg: 'bg-blue-100 dark:bg-blue-900/40',       label: 'Senior Developer' },
  Architect: { icon: Building2,   color: 'text-amber-600',   bg: 'bg-amber-100 dark:bg-amber-900/40',     label: 'Senior Architect' },
  SRE:       { icon: Server,      color: 'text-emerald-600', bg: 'bg-emerald-100 dark:bg-emerald-900/40', label: 'Senior SRE' },
  Security:  { icon: ShieldCheck, color: 'text-red-600',     bg: 'bg-red-100 dark:bg-red-900/40',         label: 'Security Expert' },
};

export default function AgentsPage() {
  const { data, isLoading, isError } = useAgentsPerformance();
  const agents = data?.agents ?? [];
  const totalScans = data?.total_scans_analysed ?? 0;

  return (
    <>
      <Header title="Agents" breadcrumbs={[{ label: 'Agents' }]} />
      <main className="flex-1 p-6 space-y-6">
        <div className="flex items-center gap-2">
          <Cpu className="h-5 w-5 text-slate-400" />
          <span className="text-sm text-slate-500">
            {isLoading ? 'Loading…' : `${totalScans} completed scan${totalScans !== 1 ? 's' : ''} analysed`}
          </span>
        </div>

        {isLoading && (
          <div className="flex items-center justify-center py-16 gap-2 text-sm text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin" />Loading agent performance…
          </div>
        )}
        {isError && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 text-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />Failed to load agent data
          </div>
        )}

        {!isLoading && !isError && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {agents.map((entry) => {
              const meta = AGENT_META[entry.name as AgentType];
              if (!meta) return null;
              const Icon = meta.icon;
              return (
                <Card key={entry.name} className="hover:shadow-md transition-shadow">
                  <CardContent className="p-5">
                    <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${meta.bg} mb-4`}>
                      <Icon className={`h-5 w-5 ${meta.color}`} />
                    </div>
                    <div className="text-sm font-semibold text-slate-800 dark:text-slate-200 mb-0.5">{meta.label}</div>
                    <div className="text-[11px] text-slate-500 mb-3">{entry.name}</div>
                    {entry.total_runs > 0 ? (
                      <>
                        <div className={`text-3xl font-black tracking-tight ${getScoreColor(Math.round(entry.avg_score))}`}>
                          {Math.round(entry.avg_score)}
                          <span className="text-sm font-normal text-slate-400">/100</span>
                        </div>
                        <div className="text-[11px] text-slate-400 mt-1">{entry.total_runs} run{entry.total_runs !== 1 ? 's' : ''}</div>
                      </>
                    ) : (
                      <div className="text-sm text-slate-400">No runs yet</div>
                    )}
                    <div className="text-xs text-slate-400 mt-3 leading-relaxed">{entry.description}</div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}

        {!isLoading && !isError && totalScans > 0 && (
          <Card>
            <CardHeader><CardTitle>Recent Agent Scores</CardTitle></CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 dark:border-slate-800">
                      <th className="text-left px-6 py-3 text-[11px] font-semibold uppercase tracking-widest text-slate-400">Repository</th>
                      <th className="text-left px-6 py-3 text-[11px] font-semibold uppercase tracking-widest text-slate-400">Date</th>
                      <th className="text-center px-4 py-3 text-[11px] font-semibold uppercase tracking-widest text-slate-400">Score</th>
                      <th className="text-left px-4 py-3 text-[11px] font-semibold uppercase tracking-widest text-slate-400">Agent</th>
                      <th className="text-left px-4 py-3 text-[11px] font-semibold uppercase tracking-widest text-slate-400">Scan</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {agents.flatMap((entry) =>
                      entry.recent_scores.slice(0, 3).map((score) => {
                        const meta = AGENT_META[entry.name as AgentType];
                        return (
                          <tr key={`${entry.name}-${score.scan_id}`} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors">
                            <td className="px-6 py-2.5 text-slate-700 dark:text-slate-300 font-medium truncate max-w-[180px]">
                              {score.repository_name}
                            </td>
                            <td className="px-6 py-2.5 text-[11px] text-slate-400">{formatDate(score.date)}</td>
                            <td className="px-4 py-2.5 text-center">
                              <span className={`text-sm font-bold ${getScoreColor(score.score)}`}>{score.score}</span>
                            </td>
                            <td className="px-4 py-2.5">
                              {meta && (
                                <span className={`inline-flex items-center gap-1 text-xs font-medium ${meta.color}`}>
                                  <meta.icon className="h-3 w-3" />{entry.name}
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-2.5">
                              <Link href={`/scans/${score.scan_id}`} className="text-[11px] text-[#ED1D24] dark:text-red-400 hover:underline font-mono">
                                {score.scan_id.slice(0, 8)}…
                              </Link>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}

        {!isLoading && !isError && totalScans === 0 && (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16 gap-2 text-sm text-slate-400">
              <Cpu className="h-10 w-10 text-slate-300 dark:text-slate-600" />
              <p>No completed scans yet. Run a scan to see agent performance.</p>
            </CardContent>
          </Card>
        )}
      </main>
    </>
  );
}
