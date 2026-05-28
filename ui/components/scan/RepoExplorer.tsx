'use client';

import { useState } from 'react';
import {
  GitBranch,
  GitPullRequest,
  Star,
  Play,
  ChevronDown,
  ChevronRight,
  Loader2,
  AlertCircle,
  GitMerge,
  FileCode,
  Clock,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useRepoBranches } from '@/hooks/useRepoBranches';
import { useRepoPulls } from '@/hooks/useRepoPulls';
import type { PullRequestItem } from '@/generated/api-client';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const d = Math.floor(diff / 86_400_000);
  if (d === 0) return 'today';
  if (d === 1) return 'yesterday';
  if (d < 30) return `${d}d ago`;
  const m = Math.floor(d / 30);
  if (m < 12) return `${m}mo ago`;
  return `${Math.floor(m / 12)}y ago`;
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface ScanButtonProps {
  onClick: () => void;
  small?: boolean;
}

function ScanButton({ onClick, small }: ScanButtonProps) {
  return (
    <button
      onClick={e => { e.stopPropagation(); onClick(); }}
      className={cn(
        'flex items-center gap-1 rounded-md font-semibold transition-all',
        'bg-[#ED1D24] text-white hover:bg-[#c41019] active:scale-95',
        small
          ? 'px-2 py-0.5 text-[10px]'
          : 'px-2.5 py-1 text-[11px]',
      )}
    >
      <Play className={cn('fill-current', small ? 'h-2.5 w-2.5' : 'h-3 w-3')} />
      Scan
    </button>
  );
}

// ─── Branch tree section ──────────────────────────────────────────────────────

interface BranchSectionProps {
  repoUrl: string;
  selectedBranch: string;
  onScan: (branch: string) => void;
}

function BranchSection({ repoUrl, selectedBranch, onScan }: BranchSectionProps) {
  const [expanded, setExpanded] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const { data, isFetching, isError } = useRepoBranches(repoUrl);

  const branches = data?.branches ?? [];
  const defaultBranch = data?.default_branch ?? '';
  const LIMIT = 8;
  const visible = showAll ? branches : branches.slice(0, LIMIT);

  return (
    <div className="select-none">
      {/* Section header */}
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors group"
      >
        {expanded
          ? <ChevronDown className="h-3.5 w-3.5 text-slate-400 shrink-0" />
          : <ChevronRight className="h-3.5 w-3.5 text-slate-400 shrink-0" />}
        <GitBranch className="h-3.5 w-3.5 text-[#ED1D24] shrink-0" />
        <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
          Branches
        </span>
        {isFetching && (
          <Loader2 className="h-3 w-3 text-slate-400 animate-spin ml-1" />
        )}
        {!isFetching && branches.length > 0 && (
          <span className="ml-1 text-[10px] text-slate-400 font-normal">({branches.length})</span>
        )}
      </button>

      {expanded && (
        <div className="ml-4 mt-0.5 border-l border-slate-200 dark:border-slate-700 pl-3 space-y-0.5">
          {isError && (
            <div className="flex items-center gap-1.5 py-1.5 text-[11px] text-amber-500">
              <AlertCircle className="h-3 w-3" />
              Could not load branches
            </div>
          )}
          {!isFetching && !isError && branches.length === 0 && (
            <p className="py-1.5 text-[11px] text-slate-400 italic">No branches found</p>
          )}
          {visible.map(b => (
            <div
              key={b}
              className={cn(
                'flex items-center gap-2 py-1 px-2 rounded-md cursor-pointer group/row transition-colors',
                selectedBranch === b
                  ? 'bg-[#ED1D24]/10 dark:bg-[#ED1D24]/15'
                  : 'hover:bg-slate-100 dark:hover:bg-slate-800',
              )}
              onClick={() => onScan(b)}
            >
              {b === defaultBranch
                ? <Star className="h-3 w-3 text-amber-400 shrink-0 fill-amber-400" />
                : <FileCode className="h-3 w-3 text-slate-400 shrink-0" />}
              <span
                className={cn(
                  'flex-1 text-[12px] truncate font-mono',
                  selectedBranch === b ? 'text-[#ED1D24] font-semibold' : 'text-slate-700 dark:text-slate-300',
                )}
                title={b}
              >
                {b}
              </span>
              {b === defaultBranch && (
                <span className="text-[9px] font-semibold uppercase tracking-wide text-amber-500 bg-amber-50 dark:bg-amber-900/30 px-1 py-0.5 rounded shrink-0">
                  default
                </span>
              )}
              <span className="opacity-0 group-hover/row:opacity-100 transition-opacity shrink-0">
                <ScanButton onClick={() => onScan(b)} small />
              </span>
            </div>
          ))}
          {branches.length > LIMIT && (
            <button
              onClick={() => setShowAll(v => !v)}
              className="mt-1 text-[11px] text-[#ED1D24] hover:underline font-medium"
            >
              {showAll ? 'Show less' : `+${branches.length - LIMIT} more branches`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ─── PR row ────────────────────────────────────────────────────────────────────

interface PRRowProps {
  pr: PullRequestItem;
  onScan: (headRef: string) => void;
}

function PRRow({ pr, onScan }: PRRowProps) {
  return (
    <div
      className="flex items-start gap-2 py-1.5 px-2 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer group/pr transition-colors"
      onClick={() => onScan(pr.head_ref)}
    >
      {/* Icon */}
      <div className="shrink-0 mt-0.5">
        {pr.draft
          ? <GitMerge className="h-3.5 w-3.5 text-slate-400" />
          : <GitPullRequest className="h-3.5 w-3.5 text-emerald-500" />}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[11px] font-mono text-slate-400 shrink-0">#{pr.number}</span>
          {pr.draft && (
            <span className="text-[9px] font-semibold uppercase tracking-wide text-slate-400 bg-slate-100 dark:bg-slate-700 px-1 py-0.5 rounded shrink-0">
              draft
            </span>
          )}
          <span className="text-[12px] text-slate-700 dark:text-slate-300 truncate font-medium" title={pr.title}>
            {pr.title}
          </span>
        </div>
        <div className="flex items-center gap-1 mt-0.5 text-[10px] text-slate-400 font-mono">
          <span className="truncate text-violet-500 dark:text-violet-400">{pr.head_ref}</span>
          <span>→</span>
          <span className="text-slate-500">{pr.base_ref}</span>
          <span className="mx-1">·</span>
          <Clock className="h-2.5 w-2.5 shrink-0" />
          <span>{timeAgo(pr.updated_at)}</span>
          <span>·</span>
          <span>{pr.author}</span>
        </div>
      </div>

      {/* Scan button */}
      <span className="opacity-0 group-hover/pr:opacity-100 transition-opacity shrink-0 mt-0.5">
        <ScanButton onClick={() => onScan(pr.head_ref)} small />
      </span>
    </div>
  );
}

// ─── PR section ───────────────────────────────────────────────────────────────

interface PRSectionProps {
  repoUrl: string;
  onScan: (headRef: string) => void;
}

function PRSection({ repoUrl, onScan }: PRSectionProps) {
  const [expanded, setExpanded] = useState(true);
  const [state, setState] = useState<'open' | 'all'>('open');
  const { data, isFetching, isError } = useRepoPulls(repoUrl, state);

  const prs = data?.pull_requests ?? [];

  return (
    <div className="select-none">
      {/* Section header */}
      <div className="flex items-center gap-1">
        <button
          onClick={() => setExpanded(v => !v)}
          className="flex flex-1 items-center gap-1.5 px-2 py-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        >
          {expanded
            ? <ChevronDown className="h-3.5 w-3.5 text-slate-400 shrink-0" />
            : <ChevronRight className="h-3.5 w-3.5 text-slate-400 shrink-0" />}
          <GitPullRequest className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
          <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-500 dark:text-slate-400">
            Pull Requests
          </span>
          {isFetching && (
            <Loader2 className="h-3 w-3 text-slate-400 animate-spin ml-1" />
          )}
          {!isFetching && prs.length > 0 && (
            <span className="ml-1 text-[10px] text-slate-400 font-normal">({prs.length})</span>
          )}
        </button>
        {/* State toggle */}
        <div className="flex rounded-md border border-slate-200 dark:border-slate-700 overflow-hidden text-[10px] font-semibold shrink-0">
          {(['open', 'all'] as const).map(s => (
            <button
              key={s}
              onClick={() => setState(s)}
              className={cn(
                'px-2 py-0.5 transition-colors capitalize',
                state === s
                  ? 'bg-[#ED1D24] text-white'
                  : 'bg-white dark:bg-slate-900 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800',
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {expanded && (
        <div className="ml-4 mt-0.5 border-l border-slate-200 dark:border-slate-700 pl-3 space-y-0.5">
          {isError && (
            <div className="flex items-center gap-1.5 py-1.5 text-[11px] text-amber-500">
              <AlertCircle className="h-3 w-3" />
              Could not load pull requests
            </div>
          )}
          {!isFetching && !isError && prs.length === 0 && (
            <p className="py-1.5 text-[11px] text-slate-400 italic">
              No {state === 'open' ? 'open ' : ''}pull requests
            </p>
          )}
          {prs.map(pr => (
            <PRRow key={pr.number} pr={pr} onScan={onScan} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

interface RepoExplorerProps {
  /** Clean base GitHub URL (no /tree/… suffix). */
  repoUrl: string;
  /** Currently selected branch in the modal (for highlight). */
  selectedBranch: string;
  /** Called when user clicks Scan on a branch or PR head-ref. */
  onScan: (branch: string) => void;
  className?: string;
}

/**
 * Tree-format explorer showing branches and pull requests for a GitHub repo.
 * Each item has a hover-revealed "Scan" button that calls ``onScan`` with the
 * relevant branch name (or PR head ref).
 *
 * Clicking anywhere on a row also calls ``onScan`` directly.
 */
export function RepoExplorer({ repoUrl, selectedBranch, onScan, className }: RepoExplorerProps) {
  return (
    <div
      className={cn(
        'rounded-xl border border-slate-200 dark:border-slate-700',
        'bg-white dark:bg-slate-900 shadow-sm overflow-hidden',
        className,
      )}
    >
      {/* Header */}
      <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800 flex items-center gap-2">
        <GitBranch className="h-3.5 w-3.5 text-[#ED1D24]" />
        <span className="text-[11px] font-semibold text-slate-600 dark:text-slate-300 truncate">
          {repoUrl.replace('https://github.com/', '')}
        </span>
        <span className="ml-auto text-[10px] text-slate-400">Click a row or hover → Scan</span>
      </div>

      {/* Tree body */}
      <div className="p-2 space-y-1 max-h-72 overflow-y-auto">
        <BranchSection repoUrl={repoUrl} selectedBranch={selectedBranch} onScan={onScan} />
        <div className="h-px bg-slate-100 dark:bg-slate-800 my-1" />
        <PRSection repoUrl={repoUrl} onScan={onScan} />
      </div>
    </div>
  );
}
