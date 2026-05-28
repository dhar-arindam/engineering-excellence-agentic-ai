'use client';

import { TestTube2, Code2, Building2, Server, ShieldCheck } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { getScoreColor } from '@/lib/utils';
import type { AgentScore, AgentType } from '@/generated/api-client';

interface AgentConfidencePanelProps {
  agents: AgentScore[];
}

const AGENT_META: Record<AgentType, { icon: React.ComponentType<{ className?: string }>; bgColor: string; iconClass: string; label: string }> = {
  QA:        { icon: TestTube2,   bgColor: '#a855f720', iconClass: 'text-purple-500',  label: 'QA' },
  Dev:       { icon: Code2,       bgColor: '#3b82f620', iconClass: 'text-blue-500',    label: 'Developer' },
  Architect: { icon: Building2,   bgColor: '#f59e0b20', iconClass: 'text-amber-500',   label: 'Architect' },
  SRE:       { icon: Server,      bgColor: '#10b98120', iconClass: 'text-emerald-500', label: 'SRE' },
  Security:  { icon: ShieldCheck, bgColor: '#ef444420', iconClass: 'text-red-500',     label: 'Security' },
};

function confidenceLabel(c: number): { label: string; color: string } {
  if (c >= 0.7) return { label: 'High',   color: 'text-emerald-600 dark:text-emerald-400' };
  if (c >= 0.5) return { label: 'Medium', color: 'text-amber-600 dark:text-amber-400' };
  return             { label: 'Low',    color: 'text-red-600 dark:text-red-400' };
}

function confidenceBarColor(c: number): string {
  if (c >= 0.7) return 'bg-emerald-500';
  if (c >= 0.5) return 'bg-amber-500';
  return 'bg-red-500';
}

export function AgentConfidencePanel({ agents }: AgentConfidencePanelProps) {
  if (!agents.length) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent Breakdown</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {agents.map((agent) => {
          const meta = AGENT_META[agent.agent as AgentType];
          const Icon = meta?.icon ?? Code2;
          const conf = agent.confidence ?? 0.5;
          const { label: confLabel, color: confColor } = confidenceLabel(conf);

          return (
            <div key={agent.agent} className="flex items-start gap-3 p-3 rounded-xl bg-slate-50 dark:bg-slate-800/40">
              <div
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                style={{ backgroundColor: meta?.bgColor ?? '#64748b20' }}
              >
                <Icon className={`h-4 w-4 ${meta?.iconClass ?? 'text-slate-500'}`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
                    {meta?.label ?? agent.agent}
                  </span>
                  <span className={`text-sm font-bold ${getScoreColor(agent.score)}`}>
                    {agent.score}
                  </span>
                </div>
                {/* Confidence bar */}
                <div className="flex items-center gap-2 mb-1">
                  <div className="flex-1 h-1 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${confidenceBarColor(conf)}`}
                      style={{ width: `${conf * 100}%` }}
                    />
                  </div>
                  <span className={`text-[10px] font-semibold shrink-0 ${confColor}`}>
                    {confLabel} {Math.round(conf * 100)}%
                  </span>
                </div>
                {/* Description / summary */}
                {agent.description && (
                  <p className="text-[11px] text-slate-400 leading-relaxed line-clamp-2">
                    {agent.description}
                  </p>
                )}
                {/* Confidence reason */}
                {agent.confidence_reason && (
                  <p className="text-[10px] text-slate-400 italic mt-0.5 line-clamp-1">
                    {agent.confidence_reason}
                  </p>
                )}
                {/* Issue count */}
                <p className="text-[10px] text-slate-400 mt-0.5">
                  {agent.issue_count} issue{agent.issue_count !== 1 ? 's' : ''}
                </p>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
