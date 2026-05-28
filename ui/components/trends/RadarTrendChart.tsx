'use client';

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { TrendDataPoint } from '@/generated/api-client';

interface RadarTrendChartProps {
  data: TrendDataPoint[];
}

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return ts;
  }
}

const DIMENSION_CONFIG: Record<string, { label: string; color: string }> = {
  readability:     { label: 'Readability',     color: '#3b82f6' },
  complexity:      { label: 'Complexity',      color: '#f59e0b' },
  reliability:     { label: 'Reliability',     color: '#10b981' },
  security:        { label: 'Security',        color: '#ef4444' },
  maintainability: { label: 'Maintainability', color: '#a855f7' },
  stability:       { label: 'Stability',       color: '#06b6d4' },
};

const DIMENSIONS = Object.keys(DIMENSION_CONFIG);

type ChartPoint = Record<string, string | number | null>;

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number | null; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const nonNull = payload.filter((p) => p.value != null);
  if (!nonNull.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lg dark:border-slate-700 dark:bg-slate-900 text-xs">
      <p className="text-slate-400 mb-1">{label}</p>
      {nonNull.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {DIMENSION_CONFIG[p.name]?.label ?? p.name}: <span className="font-bold">{p.value}/10</span>
        </p>
      ))}
    </div>
  );
}

export function RadarTrendChart({ data }: RadarTrendChartProps) {
  // Check if any data point has radar info
  const hasRadarData = data.some((pt) => pt.radar && Object.keys(pt.radar).length > 0);

  if (!data.length || !hasRadarData) {
    return (
      <Card>
        <CardHeader><CardTitle>Radar Dimensions Over Time</CardTitle></CardHeader>
        <CardContent className="flex items-center justify-center h-[260px] text-sm text-slate-400">
          Radar data appears after the first scan with full agent analysis.
        </CardContent>
      </Card>
    );
  }

  // Transform into recharts format: [{ date, readability: 7.5, complexity: null, ... }]
  const chartData: ChartPoint[] = data.map((pt) => {
    const row: ChartPoint = { date: formatTimestamp(pt.timestamp) };
    for (const dim of DIMENSIONS) {
      const dimData = (pt.radar as Record<string, { score: number | null } | undefined>)[dim];
      row[dim] = dimData?.score ?? null;
    }
    return row;
  });

  // Only show dimensions that appear in at least one point
  const activeDimensions = DIMENSIONS.filter((dim) =>
    chartData.some((pt) => pt[dim] != null)
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Radar Dimensions Over Time</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              domain={[0, 10]}
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
              ticks={[0, 2, 4, 6, 8, 10]}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
              formatter={(name) => DIMENSION_CONFIG[name]?.label ?? name}
            />
            {activeDimensions.map((dim) => (
              <Line
                key={dim}
                type="monotone"
                dataKey={dim}
                stroke={DIMENSION_CONFIG[dim].color}
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls={false}
                name={dim}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
