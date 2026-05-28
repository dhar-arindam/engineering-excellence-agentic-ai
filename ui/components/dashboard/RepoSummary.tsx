import { TrendingUp, TrendingDown, Minus, Calendar, GitCommit, Users } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import type { Repository } from '@/types';
import { formatDate, getScoreColor } from '@/lib/utils';

interface RepoSummaryProps {
  repo: Repository;
}

const riskVariant: Record<string, 'low' | 'medium' | 'high' | 'critical'> = {
  Low: 'low',
  Medium: 'medium',
  High: 'high',
  Critical: 'critical',
};

export function RepoSummary({ repo }: RepoSummaryProps) {
  const DeltaIcon =
    repo.delta > 0 ? TrendingUp : repo.delta < 0 ? TrendingDown : Minus;
  const deltaColor =
    repo.delta > 0
      ? 'text-emerald-500'
      : repo.delta < 0
        ? 'text-red-500'
        : 'text-slate-400';
  const deltaPrefix = repo.delta > 0 ? '+' : '';

  return (
    <Card className="col-span-full">
      <CardContent className="p-6">
        <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
          {/* Score block */}
          <div className="flex items-center gap-6">
            <div className="relative flex h-24 w-24 items-center justify-center rounded-2xl bg-slate-50 dark:bg-slate-800/50">
              <span className={`text-4xl font-black tracking-tighter ${getScoreColor(repo.overall_score)}`}>
                {repo.overall_score}
              </span>
              <span className="absolute bottom-2 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                Score
              </span>
            </div>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100">
                  {repo.name}
                </h2>
                <Badge variant={riskVariant[repo.risk]}>{repo.risk} Risk</Badge>
              </div>
              <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">
                {repo.description}
              </p>
              <div className={`flex items-center gap-1 mt-2 text-sm font-medium ${deltaColor}`}>
                <DeltaIcon className="h-4 w-4" />
                <span>
                  {deltaPrefix}{repo.delta} pts since last scan
                </span>
              </div>
            </div>
          </div>

          {/* Meta stats */}
          <div className="flex flex-wrap gap-4 md:gap-6">
            <Stat
              icon={Calendar}
              label="Last Scan"
              value={formatDate(repo.last_scan_date)}
            />
            <Stat
              icon={GitCommit}
              label="Open Issues"
              value={repo.open_issues.toString()}
              valueClass="text-red-500"
            />
            <Stat
              icon={Users}
              label="Team Size"
              value={`${repo.team_size} engineers`}
            />
            <Stat
              icon={GitCommit}
              label="Language"
              value={repo.language}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  valueClass = 'text-slate-900 dark:text-slate-100',
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <span className={`text-sm font-semibold ${valueClass}`}>{value}</span>
    </div>
  );
}
