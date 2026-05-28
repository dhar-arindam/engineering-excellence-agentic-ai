'use client';

import { Loader2, Trash2, AlertTriangle, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useDeleteRepository } from '@/hooks/useRepositoryCrud';
import type { RepositoryListItem } from '@/generated/api-client';

interface DeleteConfirmDialogProps {
  repo: RepositoryListItem | null;
  onClose: () => void;
}

export function DeleteConfirmDialog({ repo, onClose }: DeleteConfirmDialogProps) {
  const deleteMutation = useDeleteRepository();

  async function handleDelete() {
    if (!repo) return;
    await deleteMutation.mutateAsync(repo.id);
    onClose();
  }

  if (!repo) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-sm bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 p-6">
        <div className="flex items-start gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-100 dark:bg-red-950/40">
            <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
          </div>
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-1">Delete Repository</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Are you sure you want to remove <span className="font-medium text-slate-700 dark:text-slate-300">{repo.name}</span> from the platform?
              All scan history will be erased. <span className="text-slate-600 dark:text-slate-300 font-medium">Your actual code and repository remain completely untouched.</span>
            </p>
          </div>
          <button onClick={onClose} className="rounded p-1 hover:bg-slate-100 dark:hover:bg-slate-800">
            <X className="h-4 w-4 text-slate-400" />
          </button>
        </div>

        {deleteMutation.error && (
          <p className="mt-4 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/20 px-3 py-2 rounded-lg">
            {deleteMutation.error.message}
          </p>
        )}

        <div className="flex gap-3 mt-6">
          <Button variant="outline" onClick={onClose} className="flex-1">Cancel</Button>
          <Button
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            className="flex-1 bg-red-600 hover:bg-red-700 text-white border-red-600"
          >
            {deleteMutation.isPending && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
            <Trash2 className="h-3.5 w-3.5 mr-1.5" />
            Delete
          </Button>
        </div>
      </div>
    </div>
  );
}
