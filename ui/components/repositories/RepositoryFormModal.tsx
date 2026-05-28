'use client';

import { useState, useEffect } from 'react';
import { X, GitBranch, HardDrive, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { useCreateRepository, useUpdateRepository } from '@/hooks/useRepositoryCrud';
import type { RepositoryListItem, CreateRepositoryRequest, SourceType } from '@/generated/api-client';

interface RepositoryFormModalProps {
  open: boolean;
  onClose: () => void;
  editTarget?: RepositoryListItem;
}

export function RepositoryFormModal({ open, onClose, editTarget }: RepositoryFormModalProps) {
  const isEditing = !!editTarget;

  const [sourceType, setSourceType] = useState<SourceType>('github');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [language, setLanguage] = useState('');
  const [repoUrl, setRepoUrl] = useState('');
  const [localPath, setLocalPath] = useState('');
  const [teamSize, setTeamSize] = useState('');
  const [error, setError] = useState<string | null>(null);

  const createMutation = useCreateRepository();
  const updateMutation = useUpdateRepository(editTarget?.id ?? '');
  const isPending = createMutation.isPending || updateMutation.isPending;

  useEffect(() => {
    if (!open) return;
    if (editTarget) {
      setName(editTarget.name);
      setDescription(editTarget.description ?? '');
      setLanguage(editTarget.language ?? '');
      setSourceType(editTarget.source_type);
      setRepoUrl(editTarget.repository_url ?? '');
      setLocalPath(editTarget.local_path ?? '');
      setTeamSize(editTarget.team_size?.toString() ?? '');
    } else {
      setName(''); setDescription(''); setLanguage('');
      setSourceType('github'); setRepoUrl(''); setLocalPath(''); setTeamSize('');
    }
    setError(null);
  }, [open, editTarget]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!name.trim()) { setError('Name is required'); return; }
    if (sourceType === 'github' && !repoUrl.trim()) { setError('Repository URL is required'); return; }
    if (sourceType === 'local' && !localPath.trim()) { setError('Local path is required'); return; }

    try {
      if (isEditing) {
        await updateMutation.mutateAsync({ name, description, language, team_size: teamSize ? parseInt(teamSize) : undefined });
      } else {
        const data: CreateRepositoryRequest = {
          name,
          description: description || undefined,
          language: language || undefined,
          source_type: sourceType,
          repository_url: sourceType === 'github' ? repoUrl : undefined,
          local_path: sourceType === 'local' ? localPath : undefined,
          team_size: teamSize ? parseInt(teamSize) : undefined,
        };
        await createMutation.mutateAsync(data);
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-md bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 dark:border-slate-800">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            {isEditing ? 'Edit Repository' : 'Add Repository'}
          </h2>
          <button onClick={onClose} className="rounded-lg p-1 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
            <X className="h-4 w-4 text-slate-400" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Source type (only for create) */}
          {!isEditing && (
            <div className="grid grid-cols-2 gap-2">
              {(['github', 'local'] as SourceType[]).map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => setSourceType(type)}
                  className={cn(
                    'flex items-center gap-2 rounded-xl border px-3 py-2.5 text-sm font-medium transition-all',
                    sourceType === type
                      ? 'border-[#ED1D24] bg-red-50 text-[#ED1D24] dark:border-red-500 dark:bg-red-950/30 dark:text-red-300'
                      : 'border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800',
                  )}
                >
                  {type === 'github' ? <GitBranch className="h-4 w-4" /> : <HardDrive className="h-4 w-4" />}
                  {type === 'github' ? 'GitHub' : 'Local'}
                </button>
              ))}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">Name *</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="My Repository" />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">Description</label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional description" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">Language</label>
              <Input value={language} onChange={(e) => setLanguage(e.target.value)} placeholder="Python" />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">Team Size</label>
              <Input type="number" min="1" value={teamSize} onChange={(e) => setTeamSize(e.target.value)} placeholder="5" />
            </div>
          </div>

          {!isEditing && sourceType === 'github' && (
            <div>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">Repository URL *</label>
              <Input value={repoUrl} onChange={(e) => setRepoUrl(e.target.value)} placeholder="https://github.com/owner/repo" />
            </div>
          )}

          {!isEditing && sourceType === 'local' && (
            <div>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">Local Path *</label>
              <Input value={localPath} onChange={(e) => setLocalPath(e.target.value)} placeholder="/path/to/project" />
            </div>
          )}

          {error && (
            <p className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/20 px-3 py-2 rounded-lg">{error}</p>
          )}

          <div className="flex items-center gap-3 pt-2">
            <Button type="button" variant="outline" onClick={onClose} className="flex-1">
              Cancel
            </Button>
            <Button type="submit" disabled={isPending} className="flex-1">
              {isPending && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              {isEditing ? 'Save Changes' : 'Add Repository'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
