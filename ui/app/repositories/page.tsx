'use client';

import { useState } from 'react';
import { Plus, Loader2, AlertCircle, GitBranch } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Header } from '@/components/layout/Header';
import { RepositoryTable } from '@/components/repositories/RepositoryTable';
import { RepositoryFormModal } from '@/components/repositories/RepositoryFormModal';
import { DeleteConfirmDialog } from '@/components/repositories/DeleteConfirmDialog';
import { useRepositories } from '@/hooks/useRepositories';
import type { RepositoryListItem } from '@/generated/api-client';

export default function RepositoriesPage() {
  const { data, isLoading, isError, error } = useRepositories();
  const [formOpen, setFormOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<RepositoryListItem | undefined>(undefined);
  const [deleteTarget, setDeleteTarget] = useState<RepositoryListItem | null>(null);

  const items = data?.items ?? [];

  return (
    <>
      <Header
        title="Repositories"
        breadcrumbs={[{ label: 'Repositories' }]}
      />
      <main className="flex-1 p-6 space-y-6">
        {/* Stats bar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-slate-400" />
            <span className="text-sm text-slate-500">
              {isLoading ? '…' : `${data?.total ?? 0} repository${(data?.total ?? 0) !== 1 ? 'ies' : 'y'}`}
            </span>
          </div>
          <Button onClick={() => { setEditTarget(undefined); setFormOpen(true); }} size="sm">
            <Plus className="h-3.5 w-3.5 mr-1.5" />
            Add Repository
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>All Repositories</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {isLoading && (
              <div className="flex items-center justify-center py-16 gap-2 text-sm text-slate-400">
                <Loader2 className="h-5 w-5 animate-spin" />
                Loading repositories…
              </div>
            )}
            {isError && (
              <div className="flex items-center gap-2 mx-6 my-4 px-4 py-3 rounded-xl bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 text-sm">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error?.message ?? 'Failed to load repositories'}
              </div>
            )}
            {!isLoading && !isError && (
              <RepositoryTable
                items={items}
                onEdit={(repo) => { setEditTarget(repo); setFormOpen(true); }}
                onDelete={(repo) => setDeleteTarget(repo)}
              />
            )}
          </CardContent>
        </Card>
      </main>

      <RepositoryFormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        editTarget={editTarget}
      />
      <DeleteConfirmDialog
        repo={deleteTarget}
        onClose={() => setDeleteTarget(null)}
      />
    </>
  );
}
