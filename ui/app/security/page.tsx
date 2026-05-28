'use client';

import { ShieldCheck, AlertTriangle, Shield, Bug, Lock, ExternalLink } from 'lucide-react';
import { Loader2, AlertCircle } from 'lucide-react';
import Link from 'next/link';
import { Header } from '@/components/layout/Header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useSecurityOverview } from '@/hooks/useSecurityOverview';
import { formatDate, getScoreColor } from '@/lib/utils';

const riskColor: Record<string, string> = {
  Critical: 'bg-red-600 text-white',
  High:     'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  Medium:   'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  Low:      'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
};

export default function SecurityPage() {
  const { data, isLoading, isError } = useSecurityOverview();
  const repos = data?.repositories ?? [];

  return (
    <>
      <Header title="Security" breadcrumbs={[{ label: 'Security' }]} />
      <main className="flex-1 p-6 space-y-6">
        {/* Risk breakdown cards */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: 'Critical Risk', count: data?.critical_count ?? 0, icon: Bug,           color: 'text-red-600',    bg: 'bg-red-50 dark:bg-red-950/20' },
            { label: 'High Risk',     count: data?.high_count ?? 0,     icon: AlertTriangle,  color: 'text-orange-600', bg: 'bg-orange-50 dark:bg-orange-950/20' },
            { label: 'Medium Risk',   count: data?.medium_count ?? 0,   icon: Shield,         color: 'text-amber-600',  bg: 'bg-amber-50 dark:bg-amber-950/20' },
            { label: 'Low Risk',      count: data?.low_count ?? 0,      icon: ShieldCheck,    color: 'text-emerald-600',bg: 'bg-emerald-50 dark:bg-emerald-950/20' },
          ].map(({ label, count, icon: Icon, color, bg }) => (
            <Card key={label}>
              <CardContent className="p-5 flex items-center gap-4">
                <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${bg}`}>
                  <Icon className={`h-5 w-5 ${color}`} />
                </div>
                <div>
                  <div className={`text-2xl font-black ${color}`}>{count}</div>
                  <div className="text-xs text-slate-500">{label}</div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Security agent scores per repo */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-slate-400" />
              Security Agent Scores by Repository
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {isLoading && (
              <div className="flex items-center justify-center py-16 gap-2 text-sm text-slate-400">
                <Loader2 className="h-5 w-5 animate-spin" />Loading…
              </div>
            )}
            {isError && (
              <div className="flex items-center gap-2 mx-6 my-4 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 text-sm">
                <AlertCircle className="h-4 w-4 shrink-0" />Failed to load security data
              </div>
            )}
            {!isLoading && !isError && repos.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 gap-2 text-sm text-slate-400">
                <ShieldCheck className="h-10 w-10 text-slate-300 dark:text-slate-600" />
                <p>No completed scans with security analysis yet.</p>
              </div>
            )}
            {!isLoading && !isError && repos.length > 0 && (
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                {repos.map((repo) => (
                  <div key={repo.repository_id} className="flex items-center gap-4 px-6 py-3.5">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <Link
                          href={`/repositories/${repo.repository_id}`}
                          className="text-sm font-medium text-slate-700 dark:text-slate-300 hover:text-[#ED1D24] dark:hover:text-red-400 transition-colors"
                        >
                          {repo.repository_name}
                        </Link>
                      </div>
                      <div className="flex items-center gap-3 text-[11px] text-slate-400">
                        <span>{formatDate(repo.last_scan_date)}</span>
                        <span>·</span>
                        <span>{repo.open_issues} security issue{repo.open_issues !== 1 ? 's' : ''}</span>
                        <span>·</span>
                        <Link href={`/scans/${repo.scan_id}`} className="flex items-center gap-1 hover:text-[#ED1D24] transition-colors">
                          <ExternalLink className="h-3 w-3" />
                          view scan
                        </Link>
                      </div>
                    </div>
                    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${riskColor[repo.risk] ?? 'bg-slate-100 text-slate-600'}`}>
                      {repo.risk} Risk
                    </span>
                    <div className={`text-lg font-bold shrink-0 ${getScoreColor(repo.security_score)}`}>
                      {repo.security_score}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Security recommendations */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Lock className="h-4 w-4 text-slate-400" />Security Recommendations
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-slate-600 dark:text-slate-400">
            {[
              'Enable dependency scanning in your CI pipeline to catch vulnerabilities early.',
              'Rotate secrets and API keys regularly. Never commit credentials to source control.',
              'Review SecurityExpertAgent findings on each completed scan and address Critical findings within 24 hours.',
            ].map((tip, i) => (
              <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40">
                <ShieldCheck className="h-4 w-4 text-[#ED1D24] mt-0.5 shrink-0" />
                <p>{tip}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      </main>
    </>
  );
}
