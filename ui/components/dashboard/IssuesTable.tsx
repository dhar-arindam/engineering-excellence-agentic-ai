'use client';

import { useState, useMemo } from 'react';
import { Search, ChevronDown, ChevronUp, FileCode, AlertCircle } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { EmptyState } from '@/components/dashboard/EmptyState';
import { cn, getSeverityOrder } from '@/lib/utils';
import type { Issue, Severity, AgentType } from '@/types';

interface IssuesTableProps {
  issues: Issue[];
}

const severityVariant: Record<Severity, 'high' | 'medium' | 'low' | 'info' | 'critical'> = {
  Critical: 'critical',
  High: 'high',
  Medium: 'medium',
  Low: 'low',
  Info: 'info',
};

const agentVariant: Record<AgentType, string> = {
  QA: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  Dev: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  Architect: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  SRE: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  Security: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
};

const SEVERITIES: Array<Severity | 'All'> = ['All', 'Critical', 'High', 'Medium', 'Low', 'Info'];
const AGENTS: Array<AgentType | 'All'> = ['All', 'QA', 'Dev', 'Architect', 'SRE', 'Security'];

export function IssuesTable({ issues }: IssuesTableProps) {
  const [search, setSearch] = useState('');
  const [severityFilter, setSeverityFilter] = useState<Severity | 'All'>('All');
  const [agentFilter, setAgentFilter] = useState<AgentType | 'All'>('All');
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const filtered = useMemo(() => {
    return issues
      .filter((issue) => {
        const matchesSeverity = severityFilter === 'All' || issue.severity === severityFilter;
        const matchesAgent = agentFilter === 'All' || issue.agent === agentFilter;
        const q = search.toLowerCase();
        const matchesSearch =
          !q ||
          issue.title.toLowerCase().includes(q) ||
          issue.file_path.toLowerCase().includes(q) ||
          issue.description.toLowerCase().includes(q);
        return matchesSeverity && matchesAgent && matchesSearch;
      })
      .sort((a, b) => getSeverityOrder(a.severity) - getSeverityOrder(b.severity));
  }, [issues, search, severityFilter, agentFilter]);

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle>Issues ({filtered.length})</CardTitle>
          <div className="flex flex-wrap gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
              <Input
                placeholder="Search issues..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8 w-44"
              />
            </div>
            <Select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value as Severity | 'All')}
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s === 'All' ? 'All Severities' : s}
                </option>
              ))}
            </Select>
            <Select
              value={agentFilter}
              onChange={(e) => setAgentFilter(e.target.value as AgentType | 'All')}
            >
              {AGENTS.map((a) => (
                <option key={a} value={a}>
                  {a === 'All' ? 'All Agents' : a}
                </option>
              ))}
            </Select>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {filtered.length === 0 ? (
          <div className="p-8">
            <EmptyState
              icon={AlertCircle}
              title="No issues found"
              description="Try adjusting your filters or search query."
            />
          </div>
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {filtered.map((issue) => {
              const isExpanded = expandedIds.has(issue.id);
              return (
                <div key={issue.id} className="group">
                  {/* Row */}
                  <button
                    className="w-full flex items-start gap-3 px-5 py-3.5 text-left hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
                    onClick={() => toggleExpand(issue.id)}
                    aria-expanded={isExpanded}
                  >
                    <div className="mt-0.5 shrink-0">
                      {isExpanded ? (
                        <ChevronUp className="h-4 w-4 text-slate-400" />
                      ) : (
                        <ChevronDown className="h-4 w-4 text-slate-400" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <Badge variant={severityVariant[issue.severity]}>{issue.severity}</Badge>
                        <span className={cn('inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium', agentVariant[issue.agent])}>
                          {issue.agent}
                        </span>
                        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200 truncate">
                          {issue.title}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
                        <FileCode className="h-3 w-3 shrink-0" />
                        <span className="font-mono truncate">{issue.file_path}</span>
                        <span className="text-slate-300 dark:text-slate-600">:</span>
                        <span>{issue.line_number}</span>
                      </div>
                    </div>
                    <span className="text-[11px] text-slate-400 shrink-0 ml-2">{issue.id}</span>
                  </button>

                  {/* Expanded details */}
                  {isExpanded && (
                    <div className="px-12 pb-4 space-y-3 bg-slate-50/50 dark:bg-slate-800/20 border-t border-slate-100 dark:border-slate-800">
                      <div>
                        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-1 mt-3">
                          Description
                        </p>
                        <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">
                          {issue.description}
                        </p>
                      </div>
                      <div>
                        <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-1">
                          Recommendation
                        </p>
                        <p className="text-sm text-[#ED1D24] dark:text-red-400 leading-relaxed">
                          {issue.recommendation}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
