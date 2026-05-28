'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ExternalLink, Trash2, Pencil, GitBranch, HardDrive, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { getScoreColor, formatDate } from '@/lib/utils';
import type { RepositoryListItem } from '@/generated/api-client';

interface RepositoryTableProps {
  items: RepositoryListItem[];
  onEdit: (repo: RepositoryListItem) => void;
  onDelete: (repo: RepositoryListItem) => void;
}

const riskVariant: Record<string, 'low' | 'medium' | 'high' | 'critical'> = {
  Low: 'low',
  Medium: 'medium',
  High: 'high',
  Critical: 'critical',
};

export function RepositoryTable({ items, onEdit, onDelete }: RepositoryTableProps) {
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <GitBranch className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-3" />
        <p className="text-sm font-medium text-slate-600 dark:text-slate-400">No repositories yet</p>
        <p className="text-xs text-slate-400 mt-1">Add your first repository to get started.</p>
      </div>
    );
  }

  return (
    <div className="divide-y divide-slate-100 dark:divide-slate-800">
      {items.map((repo) => (
        <RepositoryRow key={repo.id} repo={repo} onEdit={onEdit} onDelete={onDelete} />
      ))}
    </div>
  );
}

function RepositoryRow({
  repo,
  onEdit,
  onDelete,
}: {
  repo: RepositoryListItem;
  onEdit: (repo: RepositoryListItem) => void;
  onDelete: (repo: RepositoryListItem) => void;
}) {
  const DeltaIcon = repo.delta > 0 ? TrendingUp : repo.delta < 0 ? TrendingDown : Minus;
  const deltaColor = repo.delta > 0 ? 'text-emerald-500' : repo.delta < 0 ? 'text-red-500' : 'text-slate-400';

  return (
    <div className="flex items-center gap-4 px-6 py-4 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors group">
      {/* Icon */}
      <div className="h-9 w-9 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center shrink-0">
        {repo.source_type === 'github'
          ? <GitBranch className="h-4 w-4 text-slate-500" />
          : <HardDrive className="h-4 w-4 text-slate-500" />}
      </div>

      {/* Name + meta */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Link
            href={`/repositories/${repo.id}`}
            className="text-sm font-semibold text-slate-900 dark:text-slate-100 hover:text-[#ED1D24] dark:hover:text-red-400 transition-colors"
          >
            {repo.name}
          </Link>
          <Badge variant={riskVariant[repo.risk]}>{repo.risk}</Badge>
          {repo.language && (
            <span className="text-[11px] bg-slate-100 dark:bg-slate-800 text-slate-500 px-1.5 py-0.5 rounded font-mono">
              {repo.language}
            </span>
          )}
        </div>
        {repo.description && (
          <p className="text-xs text-slate-400 mt-0.5 truncate max-w-md">{repo.description}</p>
        )}
        <p className="text-[11px] text-slate-400 mt-1">
          Last scan: {formatDate(repo.last_scan_date)} · {repo.scan_count} scan{repo.scan_count !== 1 ? 's' : ''} · {repo.open_issues} open issue{repo.open_issues !== 1 ? 's' : ''}
        </p>
      </div>

      {/* Score */}
      <div className="text-right shrink-0">
        <div className={`text-lg font-bold ${getScoreColor(repo.overall_score)}`}>{repo.overall_score}</div>
        <div className={`flex items-center justify-end gap-0.5 text-xs ${deltaColor}`}>
          <DeltaIcon className="h-3 w-3" />
          {repo.delta > 0 ? '+' : ''}{repo.delta}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
        {repo.repository_url && (
          <a href={repo.repository_url} target="_blank" rel="noopener noreferrer">
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0">
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
          </a>
        )}
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={() => onEdit(repo)}>
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30"
          onClick={() => onDelete(repo)}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}
