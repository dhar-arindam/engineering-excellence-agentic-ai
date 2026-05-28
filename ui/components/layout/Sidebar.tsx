'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  GitBranch,
  ShieldCheck,
  Settings,
  ChevronRight,
  Activity,
  Cpu,
  ScanLine,
  Loader2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useRepositories } from '@/hooks/useRepositories';

const NAV_ITEMS = [
  { href: '/',            icon: LayoutDashboard, label: 'Dashboard' },
  { href: '/repositories', icon: GitBranch,       label: 'Repositories' },
  { href: '/scans',        icon: ScanLine,         label: 'Scans' },
  { href: '/security',     icon: ShieldCheck,      label: 'Security' },
  { href: '/agents',       icon: Cpu,              label: 'Agents' },
  { href: '/settings',     icon: Settings,         label: 'Settings' },
];

export function Sidebar() {
  const pathname = usePathname();
  const { data, isLoading } = useRepositories();
  const repos = data?.items ?? [];

  return (
    <aside className="fixed inset-y-0 left-0 z-40 w-60 flex flex-col bg-[#1a0000] dark:bg-[#0d0000] border-r border-[#3d0a0a]">
      {/* Logo */}
      <div className="flex items-center gap-2.5 h-14 px-5 border-b border-[#3d0a0a]">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-[#ED1D24]">
          <Activity className="h-4 w-4 text-white" />
        </div>
        <span className="text-sm font-semibold text-white tracking-tight">
          EngineerIQ
        </span>
      </div>

      {/* Repos section */}
      <div className="px-3 pt-5 pb-2">
        <p className="px-2 text-[11px] font-semibold uppercase tracking-widest text-slate-500 mb-2">
          Repositories
        </p>
        {isLoading && (
          <div className="flex items-center gap-2 px-3 py-2 text-xs text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading…
          </div>
        )}
        {repos.map((repo) => (
          <Link
            key={repo.id}
            href={`/repositories/${repo.id}`}
            className={cn(
              'flex items-center justify-between rounded-lg px-3 py-2 text-sm transition-colors group',
              pathname.startsWith(`/repositories/${repo.id}`)
                ? 'bg-slate-800 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200',
            )}
          >
            <div className="flex items-center gap-2 truncate">
              <GitBranch className="h-3.5 w-3.5 shrink-0 text-red-400" />
              <span className="truncate text-xs">{repo.name}</span>
            </div>
            <ChevronRight className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" />
          </Link>
        ))}
        {!isLoading && repos.length === 0 && (
          <p className="px-3 py-2 text-xs text-slate-600">No repositories yet</p>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-2 space-y-0.5">
        <p className="px-2 text-[11px] font-semibold uppercase tracking-widest text-slate-500 mb-2 mt-3">
          Navigation
        </p>
        {NAV_ITEMS.map(({ href, icon: Icon, label }) => {
          const isActive =
            href === '/'
              ? pathname === href
              : pathname.startsWith(href);
          return (
            <Link
              key={label}
              href={href}
              className={cn(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-[#ED1D24]/20 text-red-300'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200',
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-4 border-t border-[#3d0a0a]">
        <div className="flex items-center gap-2.5">
          <div className="h-7 w-7 rounded-full bg-gradient-to-br from-[#ED1D24] to-[#7f1d1d] flex items-center justify-center text-xs text-white font-bold">
            E
          </div>
          <div className="min-w-0">
            <p className="text-xs font-medium text-slate-300 truncate">Engineering Team</p>
            <p className="text-[11px] text-slate-500">Pro Plan</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
