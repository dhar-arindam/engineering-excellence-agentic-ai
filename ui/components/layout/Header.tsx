'use client';

import { Bell, Search, Sun, Moon, Play, LogOut, ChevronDown, User } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { useScanModal } from '@/components/providers';
import { useAuth } from '@/components/auth/AuthProvider';
import { cn } from '@/lib/utils';

interface HeaderProps {
  title: string;
  subtitle?: string;
  breadcrumbs?: { label: string; href?: string }[];
}

// ─── Avatar helpers ───────────────────────────────────────────────────────────

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// ─── User menu dropdown ───────────────────────────────────────────────────────

function UserMenu() {
  const { user, mode, logout, isLoading } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 px-1">
        <div className="h-7 w-7 rounded-full bg-slate-200 dark:bg-slate-700 animate-pulse" />
        <div className="hidden sm:block h-3 w-20 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
      </div>
    );
  }

  const displayName = user?.name ?? 'Guest';
  const initials    = getInitials(displayName);
  const isLocal     = mode === 'local';

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex items-center gap-2 rounded-lg px-2 py-1 text-sm transition-colors',
          'hover:bg-slate-100 dark:hover:bg-slate-800',
          open && 'bg-slate-100 dark:bg-slate-800',
        )}
        aria-expanded={open}
        aria-haspopup="true"
      >
        {/* Avatar */}
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[#ED1D24] text-[11px] font-bold text-white shrink-0 select-none">
          {initials}
        </span>

        {/* Name + DEV badge */}
        <span className="hidden sm:flex items-center gap-1.5">
          <span className="text-xs font-medium text-slate-800 dark:text-slate-200 max-w-[120px] truncate">
            {displayName}
          </span>
          {isLocal && (
            <span className="rounded px-1 py-0.5 text-[9px] font-bold uppercase tracking-wider bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-400 border border-amber-300 dark:border-amber-700">
              DEV
            </span>
          )}
        </span>

        <ChevronDown className={cn(
          'h-3 w-3 text-slate-400 transition-transform duration-150',
          open && 'rotate-180',
        )} />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute right-0 top-full mt-1.5 w-56 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg shadow-slate-900/10 dark:shadow-slate-900/40 z-50">
          {/* User info */}
          <div className="px-3 py-2.5 border-b border-slate-100 dark:border-slate-800">
            <p className="text-xs font-semibold text-slate-900 dark:text-slate-100 truncate">
              {displayName}
            </p>
            {user?.email && (
              <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                {user.email}
              </p>
            )}
            {user?.roles && user.roles.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1.5">
                {user.roles.map((r) => (
                  <span key={r} className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300">
                    {r}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Local mode notice */}
          {isLocal && (
            <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800">
              <p className="text-[10px] text-slate-400 dark:text-slate-500 leading-relaxed">
                Running in <strong className="text-amber-600 dark:text-amber-400">local dev mode</strong>.
                Authentication is disabled.
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="p-1">
            {/* Profile row (always visible) */}
            <button className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
              <User className="h-3.5 w-3.5" />
              Profile
            </button>

            {/* Logout — only meaningful in Azure mode */}
            {!isLocal && (
              <button
                onClick={() => { logout(); setOpen(false); }}
                className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
              >
                <LogOut className="h-3.5 w-3.5" />
                Sign out
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Header ───────────────────────────────────────────────────────────────────

export function Header({ title, subtitle, breadcrumbs }: HeaderProps) {
  const [dark, setDark] = useState(false);
  const { openTrigger } = useScanModal();

  useEffect(() => {
    const saved = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if (saved === 'dark' || (!saved && prefersDark)) {
      document.documentElement.classList.add('dark');
      setDark(true);
    }
  }, []);

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle('dark', next);
    localStorage.setItem('theme', next ? 'dark' : 'light');
  };

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-slate-200 bg-white/80 px-6 backdrop-blur-sm dark:border-[#3d0a0a] dark:bg-[#0d0000]/80">
      {/* Left: breadcrumbs / title */}
      <div>
        {breadcrumbs && breadcrumbs.length > 0 ? (
          <nav className="flex items-center gap-1.5 text-xs text-slate-500">
            {breadcrumbs.map((crumb, i) => (
              <span key={i} className="flex items-center gap-1.5">
                {i > 0 && <span>/</span>}
                <span
                  className={
                    i === breadcrumbs.length - 1
                      ? 'text-slate-900 font-medium dark:text-slate-100'
                      : 'hover:text-slate-700 dark:hover:text-slate-300'
                  }
                >
                  {crumb.label}
                </span>
              </span>
            ))}
          </nav>
        ) : (
          <h1 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {title}
          </h1>
        )}
        {subtitle && (
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{subtitle}</p>
        )}
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-2">
        {/* Run New Scan CTA */}
        <Button
          size="sm"
          onClick={openTrigger}
          className="hidden sm:flex items-center gap-1.5 h-8 px-3 text-xs font-semibold"
        >
          <Play className="h-3 w-3" />
          Run New Scan
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="flex sm:hidden h-8 w-8"
          onClick={openTrigger}
          title="Run New Scan"
        >
          <Play className="h-4 w-4" />
        </Button>

        <div className="relative hidden md:block">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400" />
          <input
            type="search"
            placeholder="Search..."
            className="h-8 w-48 rounded-lg border border-slate-200 bg-slate-50 pl-8 pr-3 text-xs text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[#ED1D24] dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
          />
        </div>

        <Button variant="ghost" size="icon" className="h-8 w-8 relative">
          <Bell className="h-4 w-4" />
          <span className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-[#ED1D24]" />
        </Button>

        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={toggleTheme}>
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>

        {/* Divider */}
        <div className="h-5 w-px bg-slate-200 dark:bg-slate-700 mx-1" />

        {/* User identity */}
        <UserMenu />
      </div>
    </header>
  );
}

