'use client';

import { Settings, Server, Key, Globe, Database, Cpu } from 'lucide-react';
import { Header } from '@/components/layout/Header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useLocalUser } from '@/hooks/useLocalUser';

const API_URL =
  typeof window !== 'undefined'
    ? ((window as Window & { __ENV?: { NEXT_PUBLIC_API_URL?: string } }).__ENV?.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000')
    : 'http://localhost:8000';

export default function SettingsPage() {
  const { data: user } = useLocalUser();

  return (
    <>
      <Header title="Settings" breadcrumbs={[{ label: 'Settings' }]} />
      <main className="flex-1 p-6 space-y-6 max-w-3xl">
        {/* Current user */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-4 w-4 text-slate-400" />Current User
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Row label="Username" value={user?.name ?? '—'} />
            <Row label="Email"    value={user?.email ?? '—'} />
            <Row label="ID"       value={user?.id ?? '—'} mono />
          </CardContent>
        </Card>

        {/* API connection */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Globe className="h-4 w-4 text-slate-400" />API Connection
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Row label="Backend URL"  value={API_URL} mono />
            <Row label="OpenAPI Docs" value={`${API_URL}/docs`} mono link />
            <Row label="OpenAPI JSON" value={`${API_URL}/openapi.json`} mono link />
          </CardContent>
        </Card>

        {/* Configuration info */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Server className="h-4 w-4 text-slate-400" />Environment
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-slate-600 dark:text-slate-400">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40">
              <Key className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-slate-700 dark:text-slate-300 mb-0.5">OPENAI_API_KEY</p>
                <p>Required for AI agent analysis. Set in <code className="text-xs bg-slate-200 dark:bg-slate-700 px-1 rounded">.env</code> or Docker environment.</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40">
              <Database className="h-4 w-4 text-[#ED1D24] mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-slate-700 dark:text-slate-300 mb-0.5">DATABASE_URL</p>
                <p>PostgreSQL connection string. Managed by Docker Compose in development.</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/40">
              <Server className="h-4 w-4 text-emerald-500 mt-0.5 shrink-0" />
              <div>
                <p className="font-medium text-slate-700 dark:text-slate-300 mb-0.5">REDIS_URL</p>
                <p>Redis connection for job queuing and scan locks. Managed by Docker Compose.</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* About */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Settings className="h-4 w-4 text-slate-400" />About EngineerIQ
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Row label="Platform"   value="EngineerIQ — Engineering Intelligence Platform" />
            <Row label="Backend"    value="FastAPI + SQLAlchemy + Arq (Python 3.11)" />
            <Row label="Frontend"   value="Next.js 16 + React 19 + TanStack Query v5" />
            <Row label="Agents"     value="5 AI agents: QA, Dev, Architect, SRE, Security" />
          </CardContent>
        </Card>
      </main>
    </>
  );
}

function Row({ label, value, mono, link }: { label: string; value: string; mono?: boolean; link?: boolean }) {
  return (
    <div className="flex items-center gap-4 py-1.5 border-b border-slate-100 dark:border-slate-800 last:border-0">
      <span className="text-sm text-slate-500 w-36 shrink-0">{label}</span>
      {link ? (
        <a href={value} target="_blank" rel="noopener noreferrer"
          className={`text-sm text-[#ED1D24] dark:text-red-400 underline underline-offset-2 ${mono ? 'font-mono' : ''}`}>
          {value}
        </a>
      ) : (
        <span className={`text-sm text-slate-700 dark:text-slate-300 ${mono ? 'font-mono' : ''}`}>{value}</span>
      )}
    </div>
  );
}
