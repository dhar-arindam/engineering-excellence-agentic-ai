'use client';

import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Dot,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { TrendDataPoint } from '@/generated/api-client';

interface ScoreTrendChartProps {
  data: TrendDataPoint[];
}

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return ts;
  }
}

function confidenceColor(eff: number): string {
  if (eff >= 0.55) return '#10b981'; // emerald
  if (eff >= 0.35) return '#f59e0b'; // amber
  return '#ef4444';                   // red
}

type DotProps = {
  cx?: number;
  cy?: number;
  payload?: TrendDataPoint;
};

function ScoreDot({ cx, cy, payload }: DotProps) {
  if (cx == null || cy == null || !payload) return null;
  const color = confidenceColor(payload.effective_confidence);
  return <Dot cx={cx} cy={cy} r={4} fill={color} stroke="#fff" strokeWidth={1.5} />;
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ value: number; payload: TrendDataPoint }>;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const confColor = confidenceColor(d.effective_confidence);
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lg dark:border-slate-700 dark:bg-slate-900 text-xs space-y-1">
      <p className="text-slate-400">{formatTimestamp(d.timestamp)}</p>
      <p className="font-bold text-[#ED1D24]">Score: {d.overall_score}/100</p>
      <p className="text-slate-500">
        Confidence: <span className="font-semibold">{Math.round(d.overall_confidence * 100)}%</span>
      </p>
      <p style={{ color: confColor }}>
        Eff. Confidence: <span className="font-semibold">{Math.round(d.effective_confidence * 100)}%</span>
      </p>
    </div>
  );
}

export function ScoreTrendChart({ data }: ScoreTrendChartProps) {
  if (!data.length) {
    return (
      <Card>
        <CardHeader><CardTitle>Score Over Time</CardTitle></CardHeader>
        <CardContent className="flex items-center justify-center h-[220px] text-sm text-slate-400">
          No trend data yet — run more scans to build history.
        </CardContent>
      </Card>
    );
  }

  const chartData = data.map((pt) => ({
    ...pt,
    date: formatTimestamp(pt.timestamp),
    conf_pct: Math.round(pt.effective_confidence * 100),
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Score Over Time</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              yAxisId="score"
              domain={[0, 100]}
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              yAxisId="conf"
              orientation="right"
              domain={[0, 100]}
              tick={{ fontSize: 10, fill: '#94a3b8' }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine
              yAxisId="score"
              y={80}
              stroke="#10b981"
              strokeDasharray="4 4"
              label={{ value: '80', position: 'right', fontSize: 9, fill: '#10b981' }}
            />
            {/* Effective confidence as a faded amber line on right axis */}
            <Line
              yAxisId="conf"
              type="monotone"
              dataKey="conf_pct"
              stroke="#f59e0b"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              opacity={0.6}
              name="Eff. Confidence"
            />
            {/* Score line with confidence-colored dots */}
            <Line
              yAxisId="score"
              type="monotone"
              dataKey="overall_score"
              stroke="#ED1D24"
              strokeWidth={2.5}
              dot={<ScoreDot />}
              activeDot={{ r: 6, fill: '#ED1D24' }}
              name="Score"
            />
          </ComposedChart>
        </ResponsiveContainer>
        {/* Legend */}
        <div className="flex items-center gap-4 mt-2 text-[10px] text-slate-500">
          <span className="flex items-center gap-1">
            <span className="w-5 h-0.5 bg-[#ED1D24] inline-block" />
            Score
          </span>
          <span className="flex items-center gap-1">
            <span className="w-5 h-0.5 bg-[#f59e0b] opacity-60 inline-block border-dashed" />
            Eff. Confidence
          </span>
          <span className="flex items-center gap-3 ml-auto">
            {[['≥55%', '#10b981'], ['35–54%', '#f59e0b'], ['<35%', '#ef4444']].map(([label, color]) => (
              <span key={label} className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                {label}
              </span>
            ))}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
