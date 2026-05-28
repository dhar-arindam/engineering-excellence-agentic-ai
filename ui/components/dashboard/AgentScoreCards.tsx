import {
  TestTube2,
  Code2,
  Building2,
  Server,
  ShieldCheck,
  TrendingUp,
  TrendingDown,
  Minus,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { getScoreColor } from '@/lib/utils';
import type { AgentScore, AgentType } from '@/types';

interface AgentScoreCardsProps {
  agents: AgentScore[];
}

const agentConfig: Record<
  AgentType,
  { icon: React.ComponentType<{ className?: string }>; color: string; bg: string }
> = {
  QA: { icon: TestTube2, color: 'text-purple-600 dark:text-purple-400', bg: 'bg-purple-100 dark:bg-purple-900/40' },
  Dev: { icon: Code2, color: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-100 dark:bg-blue-900/40' },
  Architect: { icon: Building2, color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-100 dark:bg-amber-900/40' },
  SRE: { icon: Server, color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-100 dark:bg-emerald-900/40' },
  Security: { icon: ShieldCheck, color: 'text-red-600 dark:text-red-400', bg: 'bg-red-100 dark:bg-red-900/40' },
};

export function AgentScoreCards({ agents }: AgentScoreCardsProps) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {agents.map((agent) => (
        <AgentCard key={agent.agent} agent={agent} />
      ))}
    </div>
  );
}

function AgentCard({ agent }: { agent: AgentScore }) {
  const config = agentConfig[agent.agent];
  const Icon = config.icon;
  const DeltaIcon =
    agent.delta > 0 ? TrendingUp : agent.delta < 0 ? TrendingDown : Minus;
  const deltaColor =
    agent.delta > 0 ? 'text-emerald-500' : agent.delta < 0 ? 'text-red-500' : 'text-slate-400';
  const deltaPrefix = agent.delta > 0 ? '+' : '';

  const scorePercent = agent.score;

  return (
    <Card className="group relative overflow-hidden hover:shadow-md transition-shadow">
      {/* Score bar background */}
      <div
        className="absolute bottom-0 left-0 h-0.5 bg-gradient-to-r from-[#ED1D24] to-red-400 transition-all duration-500"
        style={{ width: `${scorePercent}%` }}
      />
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-3">
          <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${config.bg}`}>
            <Icon className={`h-4 w-4 ${config.color}`} />
          </div>
          <div className={`flex items-center gap-0.5 text-xs font-medium ${deltaColor}`}>
            <DeltaIcon className="h-3 w-3" />
            <span>{deltaPrefix}{agent.delta}</span>
          </div>
        </div>
        <div className={`text-2xl font-black tracking-tight mb-0.5 ${getScoreColor(agent.score)}`}>
          {agent.score}
          <span className="text-sm font-normal text-slate-400">/100</span>
        </div>
        <div className="text-xs font-semibold text-slate-700 dark:text-slate-300">{agent.agent}</div>
        <div className="text-[11px] text-slate-400 mt-0.5 leading-tight">{agent.description}</div>
        <div className="mt-2 text-[11px] text-slate-500">
          {agent.issue_count} issue{agent.issue_count !== 1 ? 's' : ''}
        </div>
      </CardContent>
    </Card>
  );
}
