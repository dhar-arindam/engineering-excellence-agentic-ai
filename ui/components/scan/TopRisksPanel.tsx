'use client';

import { AlertTriangle, Bug, Shield, Info } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { Issue, Severity } from '@/generated/api-client';

interface TopRisksPanelProps {
  risks: Issue[];
}

const SEVERITY_CONFIG: Record<Severity, { label: string; icon: React.ComponentType<{ className?: string }>; bg: string; text: string; dot: string }> = {
  Critical: { label: 'Critical', icon: Bug,           bg: 'bg-red-50 dark:bg-red-950/20',    text: 'text-red-700 dark:text-red-300',    dot: 'bg-red-600' },
  High:     { label: 'High',     icon: AlertTriangle, bg: 'bg-orange-50 dark:bg-orange-950/20', text: 'text-orange-700 dark:text-orange-300', dot: 'bg-orange-500' },
  Medium:   { label: 'Medium',   icon: Shield,        bg: 'bg-amber-50 dark:bg-amber-950/20', text: 'text-amber-700 dark:text-amber-300',   dot: 'bg-amber-500' },
  Low:      { label: 'Low',      icon: Shield,        bg: 'bg-blue-50 dark:bg-blue-950/20',   text: 'text-blue-700 dark:text-blue-300',    dot: 'bg-blue-500' },
  Info:     { label: 'Info',     icon: Info,          bg: 'bg-slate-50 dark:bg-slate-800/40', text: 'text-slate-600 dark:text-slate-400',  dot: 'bg-slate-400' },
};

const SEV_ORDER: Severity[] = ['Critical', 'High', 'Medium', 'Low', 'Info'];

export function TopRisksPanel({ risks }: TopRisksPanelProps) {
  if (!risks.length) return null;

  // Group by severity
  const grouped = SEV_ORDER.reduce<Record<Severity, Issue[]>>((acc, sev) => {
    acc[sev] = risks.filter((r) => r.severity === sev);
    return acc;
  }, { Critical: [], High: [], Medium: [], Low: [], Info: [] });

  const nonEmpty = SEV_ORDER.filter((s) => grouped[s].length > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bug className="h-4 w-4 text-red-500" />
          Top Risks
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {nonEmpty.map((sev) => {
          const config = SEVERITY_CONFIG[sev];
          const Icon = config.icon;
          return (
            <div key={sev}>
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className={`w-2 h-2 rounded-full ${config.dot}`} />
                <span className={`text-xs font-semibold uppercase tracking-wider ${config.text}`}>
                  {config.label}
                </span>
                <span className="text-[10px] text-slate-400">({grouped[sev].length})</span>
              </div>
              <div className="space-y-1.5 pl-3.5">
                {grouped[sev].map((issue) => (
                  <div
                    key={issue.id}
                    className={`flex gap-2 p-2.5 rounded-lg ${config.bg} border border-transparent`}
                  >
                    <Icon className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${config.text}`} />
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-slate-700 dark:text-slate-200 leading-snug">
                        {issue.title}
                      </p>
                      {issue.file_path && (
                        <p className="text-[10px] text-slate-400 font-mono truncate mt-0.5">
                          {issue.file_path}{issue.line_number ? `:${issue.line_number}` : ''}
                        </p>
                      )}
                      {issue.recommendation && (
                        <p className="text-[10px] text-slate-500 italic mt-0.5 line-clamp-1">
                          → {issue.recommendation}
                        </p>
                      )}
                    </div>
                    <span className="ml-auto text-[10px] text-slate-400 shrink-0">{issue.agent}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
