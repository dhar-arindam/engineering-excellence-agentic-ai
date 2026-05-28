import { Clock, GitCommit, TrendingUp, TrendingDown, Minus, ChevronRight } from 'lucide-react';
import Link from 'next/link';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { ScanSummary } from '@/types';
import { formatDate, getScoreColor } from '@/lib/utils';

interface ScanHistoryProps {
  scans: ScanSummary[];
  activeScanId?: string;
}

const riskVariant: Record<string, 'low' | 'medium' | 'high' | 'critical'> = {
  Low: 'low',
  Medium: 'medium',
  High: 'high',
  Critical: 'critical',
};

export function ScanHistory({ scans, activeScanId }: ScanHistoryProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Scan History</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          {scans.map((scan, index) => {
            const DeltaIcon =
              scan.delta > 0 ? TrendingUp : scan.delta < 0 ? TrendingDown : Minus;
            const deltaColor =
              scan.delta > 0
                ? 'text-emerald-500'
                : scan.delta < 0
                  ? 'text-red-500'
                  : 'text-slate-400';
            const isActive = scan.id === activeScanId;
            const isLatest = index === 0;

            return (
              <Link
                key={scan.id}
                href={`/scans/${scan.id}`}
                className={`flex items-center gap-4 px-5 py-3.5 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors ${
                  isActive ? 'bg-[#ED1D24]/10 dark:bg-[#ED1D24]/10' : ''
                }`}
              >
                {/* Timeline dot */}
                <div className="flex flex-col items-center">
                  <div
                    className={`h-2.5 w-2.5 rounded-full ${
                      isLatest ? 'bg-[#ED1D24]' : 'bg-slate-300 dark:bg-slate-600'
                    }`}
                  />
                  {index < scans.length - 1 && (
                    <div className="w-px h-6 bg-slate-200 dark:bg-slate-700 mt-1" />
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                      {formatDate(scan.date)}
                    </span>
                    {isLatest && (
                      <span className="text-[10px] font-medium bg-red-100 text-[#ED1D24] dark:bg-red-900/40 dark:text-red-400 px-1.5 py-0.5 rounded-full">
                        Latest
                      </span>
                    )}
                    <Badge variant={riskVariant[scan.risk]}>{scan.risk}</Badge>
                  </div>
                  <div className="flex items-center gap-3 text-[11px] text-slate-400">
                    <span className="flex items-center gap-1">
                      <GitCommit className="h-3 w-3" />
                      {scan.commit_sha}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {scan.duration}
                    </span>
                    <span>{scan.issue_count} issues</span>
                  </div>
                </div>

                {/* Score + delta */}
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <div className={`text-lg font-bold ${getScoreColor(scan.overall_score)}`}>
                      {scan.overall_score}
                    </div>
                    <div className={`flex items-center justify-end gap-0.5 text-xs ${deltaColor}`}>
                      <DeltaIcon className="h-3 w-3" />
                      {scan.delta > 0 ? '+' : ''}{scan.delta}
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-slate-300 dark:text-slate-600" />
                </div>
              </Link>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
