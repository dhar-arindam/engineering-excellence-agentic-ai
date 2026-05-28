import { ArrowUpRight, ArrowDownRight, Minus, GitBranch, Layers, Link2 } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import type { ArchitectureDrift } from '@/types';

interface DriftPanelProps {
  drift: ArchitectureDrift;
}

export function DriftPanel({ drift }: DriftPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Architecture Drift</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <DriftRow
          icon={GitBranch}
          label="Circular Dependencies"
          delta={drift.circular_dependency_delta}
          previous={drift.previous_circular}
          current={drift.current_circular}
          unit=""
          higherIsBad
        />
        <DriftRow
          icon={Layers}
          label="Layer Violations"
          delta={drift.layer_violations_delta}
          previous={drift.previous_violations}
          current={drift.current_violations}
          unit=""
          higherIsBad
        />
        <DriftRow
          icon={Link2}
          label="Coupling Change"
          deltaStr={drift.coupling_delta}
          previous={null}
          current={null}
          unit="%"
          higherIsBad
        />
      </CardContent>
    </Card>
  );
}

interface DriftRowProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  delta?: number;
  deltaStr?: string;
  previous: number | null;
  current: number | null;
  unit: string;
  higherIsBad?: boolean;
}

function DriftRow({
  icon: Icon,
  label,
  delta,
  deltaStr,
  previous,
  current,
  higherIsBad = true,
}: DriftRowProps) {
  const rawDelta = delta ?? (deltaStr ? parseFloat(deltaStr) : 0);
  const isWorse = higherIsBad ? rawDelta > 0 : rawDelta < 0;
  const isBetter = higherIsBad ? rawDelta < 0 : rawDelta > 0;
  const isNeutral = rawDelta === 0;

  const DeltaIcon = isNeutral ? Minus : isWorse ? ArrowUpRight : ArrowDownRight;
  const deltaColor = isNeutral
    ? 'text-slate-400'
    : isWorse
      ? 'text-red-500'
      : 'text-emerald-500';
  const badgeColor = isNeutral
    ? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
    : isWorse
      ? 'bg-red-50 text-red-600 dark:bg-red-950/40 dark:text-red-400'
      : 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400';

  const displayDelta = deltaStr ?? (delta !== undefined ? (delta > 0 ? `+${delta}` : `${delta}`) : '0');

  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-100 p-3 dark:border-slate-800">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800">
        <Icon className="h-4 w-4 text-slate-500 dark:text-slate-400" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-slate-700 dark:text-slate-300">{label}</p>
        {previous !== null && current !== null && (
          <p className="text-[11px] text-slate-400 mt-0.5">
            {previous} → {current}
          </p>
        )}
      </div>
      <div className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold ${badgeColor}`}>
        <DeltaIcon className={`h-3 w-3 ${deltaColor}`} />
        {displayDelta}
      </div>
    </div>
  );
}
