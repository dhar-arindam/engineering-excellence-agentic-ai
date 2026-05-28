'use client';

import {
  RadarChart as RechartsRadar,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { RadarData } from '@/generated/api-client';

interface ScanRadarChartProps {
  radar: Partial<RadarData>;
}

const DIMENSION_LABELS: Record<string, string> = {
  readability:     'Readability',
  complexity:      'Complexity',
  reliability:     'Reliability',
  security:        'Security',
  maintainability: 'Maintainability',
  stability:       'Stability',
};

function confidenceColor(confidence: number): string {
  if (confidence >= 0.7) return '#10b981'; // green
  if (confidence >= 0.5) return '#f59e0b'; // amber
  return '#ef4444'; // red
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: any[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-lg dark:border-slate-700 dark:bg-slate-900 text-xs">
      <p className="font-semibold text-slate-700 dark:text-slate-200 mb-1">{d.label}</p>
      <p className="text-slate-600 dark:text-slate-300">Score: <span className="font-bold">{d.score}/10</span></p>
      <p style={{ color: confidenceColor(d.rawConfidence) }}>
        Confidence: {Math.round(d.rawConfidence * 100)}%
      </p>
    </div>
  );
}

export function ScanRadarChart({ radar }: ScanRadarChartProps) {
  const dimensions = Object.keys(DIMENSION_LABELS);
  const chartData = dimensions.map((key) => {
    const dim = (radar as Record<string, { score: number; confidence: number }>)[key];
    return {
      label: DIMENSION_LABELS[key],
      score: dim?.score ?? 0,
      rawConfidence: dim?.confidence ?? 0,
      // Use confidence as opacity hint for the dot color (encoded in the value itself)
    };
  });

  const hasData = chartData.some((d) => d.score > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Engineering Radar</CardTitle>
      </CardHeader>
      <CardContent>
        {!hasData ? (
          <div className="flex items-center justify-center h-[220px] text-sm text-slate-400">
            No radar data yet (run a scan to populate)
          </div>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={220}>
              <RechartsRadar data={chartData} cx="50%" cy="50%" outerRadius="75%">
                <PolarGrid stroke="#e2e8f0" />
                <PolarAngleAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: '#94a3b8' }}
                />
                <Tooltip content={<CustomTooltip />} />
                <Radar
                  dataKey="score"
                  stroke="#ED1D24"
                  fill="#ED1D24"
                  fillOpacity={0.18}
                  strokeWidth={2}
                  dot={{ r: 3, fill: '#ED1D24' }}
                />
              </RechartsRadar>
            </ResponsiveContainer>
            {/* Confidence legend per dimension */}
            <div className="grid grid-cols-3 gap-1.5 mt-2">
              {chartData.map((d) => (
                <div key={d.label} className="flex items-center gap-1 text-[10px] text-slate-500">
                  <span
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ backgroundColor: confidenceColor(d.rawConfidence) }}
                  />
                  <span className="truncate">{d.label}</span>
                  <span className="ml-auto font-medium" style={{ color: confidenceColor(d.rawConfidence) }}>
                    {Math.round(d.rawConfidence * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
