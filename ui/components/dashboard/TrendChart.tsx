'use client';

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from 'recharts';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import type { TrendPoint } from '@/types';

interface TrendChartProps {
  data: TrendPoint[];
  currentScore: number;
}

interface TooltipPayload {
  value: number;
  payload: TrendPoint;
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayload[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className="text-sm font-bold text-[#ED1D24]">
        Score: {payload[0].value}
      </p>
      <p className="text-[11px] text-slate-400">{payload[0].payload.date}</p>
    </div>
  );
}

export function TrendChart({ data, currentScore }: TrendChartProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Score Trend</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
            <defs>
              <linearGradient id="trendGradient" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#ED1D24" />
                <stop offset="100%" stopColor="#f87171" />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" className="dark:[stroke:#1e293b]" />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              domain={[50, 100]}
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine
              y={80}
              stroke="#10b981"
              strokeDasharray="4 4"
              label={{ value: 'Target 80', position: 'right', fontSize: 10, fill: '#10b981' }}
            />
            <Line
              type="monotone"
              dataKey="score"
              stroke="url(#trendGradient)"
              strokeWidth={2.5}
              dot={{ r: 4, fill: '#ED1D24', strokeWidth: 2, stroke: '#fff' }}
              activeDot={{ r: 6, fill: '#ED1D24' }}
            />
          </LineChart>
        </ResponsiveContainer>
        <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
          <span>Last 5 scans</span>
          <span className="font-medium text-[#ED1D24]">Current: {currentScore}</span>
        </div>
      </CardContent>
    </Card>
  );
}
