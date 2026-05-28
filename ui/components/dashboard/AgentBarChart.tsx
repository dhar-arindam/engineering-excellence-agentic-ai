'use client';

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from 'recharts';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import type { AgentScore } from '@/types';

interface AgentBarChartProps {
  agents: AgentScore[];
}

const agentColors: Record<string, string> = {
  QA: '#a855f7',
  Dev: '#3b82f6',
  Architect: '#f59e0b',
  SRE: '#10b981',
  Security: '#ef4444',
};

interface TooltipPayload {
  payload: AgentScore;
  value: number;
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="text-xs font-semibold text-slate-700 dark:text-slate-200 mb-1">{d.agent} Agent</p>
      <p className="text-sm font-bold" style={{ color: agentColors[d.agent] }}>
        Score: {d.score}
      </p>
      <p className="text-[11px] text-slate-400">{d.issue_count} issues</p>
    </div>
  );
}

export function AgentBarChart({ agents }: AgentBarChartProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent Breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={agents} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
            <XAxis
              dataKey="agent"
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(148,163,184,0.1)' }} />
            <Bar dataKey="score" radius={[6, 6, 0, 0]} maxBarSize={40}>
              {agents.map((entry) => (
                <Cell key={entry.agent} fill={agentColors[entry.agent] ?? '#64748b'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
