'use client';

import { Loader2, AlertCircle, GitBranch, ScanLine, TrendingUp, AlertTriangle } from 'lucide-react';
import Link from 'next/link';
import { Card, CardContent } from '@/components/ui/card';
import { Header } from '@/components/layout/Header';
import { useRepositories } from '@/hooks/useRepositories';
import { useScans } from '@/hooks/useScans';
import { getScoreColor, formatDate } from '@/lib/utils';

export default function DashboardPage() {
  const { data: reposData, isLoading: reposLoading, isError: reposError } = useRepositories();
  const { data: scansData, isLoading: scansLoading } = useScans({ limit: 5 });

  const repos = reposData?.items ?? [];
  const scans = scansData?.items ?? [];

  const avgScore = repos.length
    ? Math.round(repos.reduce((s, r) => s + r.overall_score, 0) / repos.length)
    : null;

  const highRiskCount = repos.filter((r) => r.risk === 'High' || r.risk === 'Critical').length;
  const isLoading = reposLoading || scansLoading;

  return (
    <>
      <Header title="Dashboard" breadcrumbs={[{ label: 'Dashboard' }]} />
      <main className="flex-1 p-6 space-y-6">
        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading…
          </div>
        )}

        {reposError && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 text-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />
            Failed to load data. Is the backend running?
          </div>
        )}

        {!isLoading && (
          <>
            {/* Stats cards */}
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard
                icon={GitBranch}
                label="Repositories"
                value={reposData?.total ?? 0}
                iconColor="text-[#ED1D24]"
                iconBg="bg-red-100 dark:bg-red-900/40"
              />
              <StatCard
                icon={ScanLine}
                label="Total Scans"
                value={scansData?.total ?? 0}
                iconColor="text-purple-500"
                iconBg="bg-purple-100 dark:bg-purple-900/40"
              />
              <StatCard
                icon={TrendingUp}
                label="Avg Score"
                value={avgScore !== null ? avgScore : '–'}
                valueClass={avgScore !== null ? getScoreColor(avgScore) : 'text-slate-400'}
                iconColor="text-emerald-500"
                iconBg="bg-emerald-100 dark:bg-emerald-900/40"
              />
              <StatCard
                icon={AlertTriangle}
                label="At Risk"
                value={highRiskCount}
                valueClass={highRiskCount > 0 ? 'text-red-600 dark:text-red-400' : 'text-slate-900 dark:text-slate-100'}
                iconColor="text-red-500"
                iconBg="bg-red-100 dark:bg-red-900/40"
              />
            </div>

            {/* Recent scans */}
            <section>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Recent Scans</h2>
                <Link href="/scans" className="text-xs text-[#ED1D24] dark:text-red-400 hover:underline">View all</Link>
              </div>
              {scans.length === 0 ? (
                <Card>
                  <CardContent className="flex flex-col items-center py-10 text-sm text-slate-400">
                    <ScanLine className="h-8 w-8 text-slate-300 dark:text-slate-600 mb-2" />
                    No scans yet. Add a repository and run a scan.
                  </CardContent>
                </Card>
              ) : (
                <Card>
                  <CardContent className="p-0">
                    <div className="divide-y divide-slate-100 dark:divide-slate-800">
                      {scans.map((scan) => (
                        <Link
                          key={scan.id}
                          href={`/scans/${scan.id}`}
                          className="flex items-center gap-4 px-5 py-3.5 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
                        >
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{scan.repository_name}</p>
                            <p className="text-[11px] text-slate-400 mt-0.5">{formatDate(scan.date)} · {scan.branch}</p>
                          </div>
                          <div className="flex items-center gap-3 shrink-0">
                            <span className="text-[11px] text-slate-400">{scan.issue_count} issues</span>
                            <span className={`text-sm font-bold ${getScoreColor(scan.overall_score)}`}>{scan.overall_score}</span>
                          </div>
                        </Link>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </section>

            {/* Repository list */}
            <section>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Repositories</h2>
                <Link href="/repositories" className="text-xs text-[#ED1D24] dark:text-red-400 hover:underline">Manage</Link>
              </div>
              {repos.length === 0 ? (
                <Card>
                  <CardContent className="flex flex-col items-center py-10 text-sm text-slate-400">
                    <GitBranch className="h-8 w-8 text-slate-300 dark:text-slate-600 mb-2" />
                    No repositories yet.{' '}
                    <Link href="/repositories" className="text-[#ED1D24] dark:text-red-400 hover:underline">Add one</Link>.
                  </CardContent>
                </Card>
              ) : (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {repos.map((repo) => (
                    <Link key={repo.id} href={`/repositories/${repo.id}`}>
                      <Card className="hover:shadow-md transition-shadow cursor-pointer h-full">
                        <CardContent className="p-4">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate">{repo.name}</p>
                              {repo.description && (
                                <p className="text-[11px] text-slate-400 mt-0.5 line-clamp-2">{repo.description}</p>
                              )}
                              <p className="text-[11px] text-slate-400 mt-2">{repo.language} · {repo.open_issues} issues</p>
                            </div>
                            <span className={`text-lg font-bold shrink-0 ${getScoreColor(repo.overall_score)}`}>{repo.overall_score}</span>
                          </div>
                        </CardContent>
                      </Card>
                    </Link>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </main>
    </>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  iconColor,
  iconBg,
  valueClass = 'text-slate-900 dark:text-slate-100',
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
  iconColor: string;
  iconBg: string;
  valueClass?: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-3">
          <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${iconBg} shrink-0`}>
            <Icon className={`h-4 w-4 ${iconColor}`} />
          </div>
          <div>
            <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
            <p className={`text-xl font-bold ${valueClass}`}>{value}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
