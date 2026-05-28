'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import ignore from 'ignore';
import {
  Globe,
  FolderOpen,
  X,
  ChevronDown,
  Clock,
  AlertCircle,
  Loader2,
  GitBranch,
  Settings2,
  ChevronRight,
  Zap,
  GitCommitHorizontal,
  ShieldCheck,
  Layers,
  Play,
  Upload,
  FileArchive,
  CheckCircle2,
} from 'lucide-react';
import { useRunScan } from '@/hooks/useRunScan';
import { useUploadScan } from '@/hooks/useUploadScan';
import { useRepoBranches } from '@/hooks/useRepoBranches';
import { RepoExplorer } from '@/components/scan/RepoExplorer';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScanModeSelector } from '@/components/scan/ScanModeSelector';
import { cn } from '@/lib/utils';
import type { ScanSourceType, ScanMode, ScanDepth, ScanConfig, ScanOperationMode, RecentRepo, EstimatedTime } from '@/types/scan';
import type { AgentType } from '@/types';

// ─── localStorage helpers ─────────────────────────────────────────────────────

const STORAGE_KEY = 'iq-recent-scans';

function getRecentRepos(): RecentRepo[] {
  if (typeof window === 'undefined') return [];
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as RecentRepo[];
  } catch {
    return [];
  }
}

function saveRecentRepo(repo: RecentRepo): void {
  const existing = getRecentRepos();
  const deduped = existing.filter(r => r.value !== repo.value);
  localStorage.setItem(STORAGE_KEY, JSON.stringify([repo, ...deduped].slice(0, 5)));
}

// ─── Estimated time ───────────────────────────────────────────────────────────

function getEstimatedTime(config: ScanConfig): EstimatedTime {
  if (config.mode === 'quick')
    return { min: 30, max: 60, label: '30–60 sec' };
  if (config.mode === 'security_only')
    return { min: 60, max: 120, label: '1–2 min' };

  const baseRanges: Record<ScanDepth, [number, number]> = {
    shallow: [90, 150],
    standard: [180, 300],
    deep: [480, 900],
  };
  const [lo, hi] = baseRanges[config.depth];
  const factor = Math.max(config.agents.length, 1) / 5;
  const min = Math.ceil((lo * factor) / 60);
  const max = Math.ceil((hi * factor) / 60);
  return { min, max, label: min === max ? `~${min} min` : `${min}–${max} min` };
}

// ─── File upload helpers ──────────────────────────────────────────────────────

const EXCLUDED_DIR_NAMES = new Set([
  'node_modules', '.git', '__pycache__', '.next', 'dist', 'build',
  '.mypy_cache', '.pytest_cache', 'coverage', '.tox', 'venv', '.venv',
  'vendor', 'bower_components', '.turbo', '.nuxt', '.output',
]);

function getWebkitRelPath(f: File): string {
  return ((f as File & { webkitRelativePath?: string }).webkitRelativePath ?? f.name)
    .replace(/\\/g, '/');
}

function isHardExcluded(relativePath: string): boolean {
  const parts = relativePath.replace(/\\/g, '/').split('/');
  return parts.some(part => EXCLUDED_DIR_NAMES.has(part));
}

/**
 * Parse .gitignore files from the uploaded FileList and return a filtered
 * array with gitignored files removed.
 *
 * Each .gitignore applies to files within its own directory and subdirectories.
 * Uses the `ignore` package for spec-compliant pattern matching (supports
 * negation, **, ?, character ranges, etc.).
 */
async function applyGitignoreFilter(
  files: File[],
  rootFolderName: string,
): Promise<{ filtered: File[]; gitignoreRemovedCount: number }> {
  // Find all .gitignore files in the upload.
  const gitignoreFiles = files.filter(f => {
    const parts = getWebkitRelPath(f).split('/');
    return parts[parts.length - 1] === '.gitignore';
  });

  if (!gitignoreFiles.length) {
    return { filtered: files, gitignoreRemovedCount: 0 };
  }

  // Read and build per-directory matchers.
  // dir = path relative to project root (e.g. '' for root, 'src' for src/.gitignore)
  const matchers: Array<{ dir: string; ig: ReturnType<typeof ignore> }> =
    await Promise.all(
      gitignoreFiles.map(async (gf) => {
        const relPath = getWebkitRelPath(gf);
        const parts = relPath.split('/');
        // Strip root folder name (parts[0]) and filename (last part)
        const dirParts = parts.slice(1, -1);
        const dir = dirParts.join('/');
        const content = await gf.text();
        return { dir, ig: ignore().add(content) };
      }),
    );

  let gitignoreRemovedCount = 0;
  const filtered = files.filter(f => {
    const relPath = getWebkitRelPath(f);
    // Project-relative path: strip the root folder prefix.
    const parts = relPath.split('/');
    const filePath = parts.slice(1).join('/'); // e.g. 'src/app.py'

    for (const { dir, ig } of matchers) {
      let testPath: string;
      if (dir === '') {
        // Root .gitignore — test the full project-relative path.
        testPath = filePath;
      } else if (filePath.startsWith(dir + '/')) {
        // Nested .gitignore — test relative to its directory.
        testPath = filePath.slice(dir.length + 1);
      } else {
        continue; // This gitignore doesn't apply to this file.
      }

      try {
        if (ig.ignores(testPath)) {
          gitignoreRemovedCount++;
          return false;
        }
      } catch {
        // ignore library throws for empty/invalid paths — just skip.
      }
    }
    return true;
  });

  return { filtered, gitignoreRemovedCount };
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ─── GitHub URL parser ────────────────────────────────────────────────────────

/**
 * Parse a GitHub web URL that may include /tree/{branch}[/subdir] or /blob/{branch}/file.
 * Returns { baseUrl: "https://github.com/owner/repo", branch: "branch-name" }.
 * For plain clone URLs (no /tree/ or /blob/), branch is ''.
 *
 * Examples:
 *   https://github.com/owner/repo/tree/main           → baseUrl=…/repo, branch=main
 *   https://github.com/owner/repo/tree/feature/foo    → baseUrl=…/repo, branch=feature/foo
 *   https://github.com/owner/repo.git                 → baseUrl=…/repo, branch=''
 */
function parseGitHubUrl(url: string): { baseUrl: string; branch: string } {
  const trimmed = url.trim().replace(/\.git$/, '');
  // Match /tree/{branch} — take everything after /tree/ as branch (may include slashes)
  const treeMatch = trimmed.match(
    /^(https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)\/tree\/(.+)$/
  );
  if (treeMatch) {
    return { baseUrl: treeMatch[1], branch: treeMatch[2].replace(/\/$/, '') };
  }
  // /blob/ URLs point to a file — strip to base URL only
  const blobMatch = trimmed.match(
    /^(https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)\/blob\/.+$/
  );
  if (blobMatch) {
    return { baseUrl: blobMatch[1], branch: '' };
  }
  return { baseUrl: trimmed, branch: '' };
}

// ─── Validation ───────────────────────────────────────────────────────────────

function validate(sourceType: ScanSourceType, value: string, hasFiles: boolean): string | null {
  if (sourceType === 'github') {
    if (!value.trim()) return 'Repository URL is required';
    if (!value.startsWith('https://github.com/'))
      return 'Must start with https://github.com/';
    const parts = value.replace('https://github.com/', '').split('/').filter(Boolean);
    if (parts.length < 2) return 'Must include owner and repository name';
  } else {
    if (!hasFiles) return 'Please select a folder or ZIP file';
  }
  return null;
}

// ─── Static config data ───────────────────────────────────────────────────────

const ALL_AGENTS: AgentType[] = ['QA', 'Dev', 'Architect', 'SRE', 'Security'];

const DEFAULT_CONFIG: ScanConfig = {
  mode: 'standard',
  depth: 'standard',
  agents: [...ALL_AGENTS],
  operation_mode: 'analyze',
};

interface ModeOption {
  value: ScanMode;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  desc: string;
  time: string;
}

const MODES: ModeOption[] = [
  { value: 'quick', icon: Zap, label: 'Quick', desc: 'Critical files only', time: '30–60 s' },
  { value: 'standard', icon: GitCommitHorizontal, label: 'Standard', desc: 'Full source analysis', time: '2–5 min' },
  { value: 'security_only', icon: ShieldCheck, label: 'Security', desc: 'Security agent only', time: '1–2 min' },
  { value: 'deep', icon: Layers, label: 'Deep', desc: 'Exhaustive scan', time: '8–15 min' },
];

const DEPTHS: { value: ScanDepth; label: string; sub: string }[] = [
  { value: 'shallow', label: 'Shallow', sub: 'Top-level files' },
  { value: 'standard', label: 'Standard', sub: 'Main source dirs' },
  { value: 'deep', label: 'Deep', sub: 'All files' },
];

// ─── Component ────────────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onClose: () => void;
  onStarted: (scanId: string, repositoryId: string) => void;
  initialPreset?: { sourceType: ScanSourceType; url?: string; name?: string };
}

export function ScanTriggerModal({ open, onClose, onStarted, initialPreset }: Props) {
  const [sourceType, setSourceType] = useState<ScanSourceType>('github');
  const [inputValue, setInputValue] = useState('');
  const [branch, setBranch] = useState('');
  const [config, setConfig] = useState<ScanConfig>(DEFAULT_CONFIG);
  const [touched, setTouched] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [showRecent, setShowRecent] = useState(false);
  const [recentRepos, setRecentRepos] = useState<RecentRepo[]>([]);
  // Upload state
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [selectedFolderName, setSelectedFolderName] = useState('');
  const [gitignoreFilteredCount, setGitignoreFilteredCount] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const zipInputRef = useRef<HTMLInputElement>(null);

  // Capture preset at mount — never use as effect dependency to avoid loops.
  const initialPresetRef = useRef(initialPreset);

  const { mutate: runScan, isPending: runPending, error: runError, reset: resetRunMutation } = useRunScan();
  const { mutate: uploadScan, isPending: uploadPending, error: uploadError, reset: resetUploadMutation } = useUploadScan();

  const isPending = runPending || uploadPending;
  const anyError = runError ?? uploadError;

  const {
    data: branchData,
    isFetching: branchesFetching,
    isError: branchError,
  } = useRepoBranches(sourceType === 'github' ? inputValue : '');

  // Set default branch when branches first load
  useEffect(() => {
    if (branchData?.default_branch && !branch) {
      setBranch(branchData.default_branch);
    }
  }, [branchData, branch]);

  // Reset state on open — apply any preset values from the repository detail page.
  useEffect(() => {
    if (!open) return;
    const preset = initialPresetRef.current;
    setRecentRepos(getRecentRepos());
    setTouched(false);
    setSourceType(preset?.sourceType ?? 'github');
    setInputValue(preset?.sourceType === 'github' ? (preset?.url ?? '') : '');
    setBranch('');
    setConfig(DEFAULT_CONFIG);
    setConfigOpen(false);
    setShowRecent(false);
    setSelectedFiles([]);
    setSelectedFolderName(preset?.sourceType === 'local' ? (preset?.name ?? '') : '');
    setGitignoreFilteredCount(0);
    resetRunMutation();
    resetUploadMutation();
    setTimeout(() => inputRef.current?.focus(), 60);
  }, [open, resetRunMutation, resetUploadMutation]);

  // Esc to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const validationError = touched ? validate(sourceType, inputValue, selectedFiles.length > 0) : null;
  const isValid = validate(sourceType, inputValue, selectedFiles.length > 0) === null;
  const estimated = getEstimatedTime(config);
  const filteredRecent = recentRepos.filter(r => r.source_type === sourceType);

  const hasBranches = (branchData?.branches.length ?? 0) > 0;
  const showManualBranch = sourceType === 'github' && isValid && !branchesFetching && !hasBranches && !branchError && inputValue;

  const handleModeChange = useCallback((mode: ScanMode) => {
    setConfig(c => ({
      ...c,
      mode,
      agents: mode === 'security_only' ? ['Security'] : ALL_AGENTS,
    }));
  }, []);

  const toggleAgent = useCallback((agent: AgentType) => {
    setConfig(c => ({
      ...c,
      agents: c.agents.includes(agent)
        ? c.agents.filter(a => a !== agent)
        : [...c.agents, agent],
    }));
  }, []);

  const handleFolderSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    // Copy file refs synchronously before any await (event is nullified after async boundary).
    const fileList = Array.from(e.target.files ?? []);
    if (!fileList.length) return;
    const firstRelPath = getWebkitRelPath(fileList[0]);
    const folderName = firstRelPath.split('/')[0] || fileList[0].name;

    // Step 1: apply hardcoded directory exclusions.
    const afterHardcoded = fileList.filter(f => {
      const rel = getWebkitRelPath(f);
      const withoutRoot = rel.includes('/') ? rel.split('/').slice(1).join('/') : rel;
      return !isHardExcluded(withoutRoot);
    });

    // Step 2: apply .gitignore rules from the uploaded folder.
    const { filtered, gitignoreRemovedCount } = await applyGitignoreFilter(afterHardcoded, folderName);

    setSelectedFolderName(folderName);
    setSelectedFiles(filtered);
    setGitignoreFilteredCount(gitignoreRemovedCount);
    setTouched(true);
    resetRunMutation();
    resetUploadMutation();
  }, [resetRunMutation, resetUploadMutation]);

  const handleZipSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSelectedFolderName(file.name.replace(/\.zip$/i, ''));
    setSelectedFiles([file]);
    setTouched(true);
    resetRunMutation();
    resetUploadMutation();
  }, [resetRunMutation, resetUploadMutation]);

  const clearUploadSelection = useCallback(() => {
    setSelectedFiles([]);
    setSelectedFolderName('');
    setGitignoreFilteredCount(0);
    if (folderInputRef.current) folderInputRef.current.value = '';
    if (zipInputRef.current) zipInputRef.current.value = '';
  }, []);

  const handleSubmit = () => {
    setTouched(true);
    if (!isValid) return;

    if (sourceType === 'github') {
      const req = {
        source_type: sourceType,
        repository_url: inputValue.trim(),
        ...(branch ? { branch } : {}),
        config,
      };
      runScan(req, {
        onSuccess: data => {
          saveRecentRepo({
            value: inputValue.trim(),
            source_type: sourceType,
            label: inputValue.trim()
              .replace('https://github.com/', '')
              .split('/')
              .slice(0, 2)
              .join('/'),
            last_used: new Date().toISOString(),
            ...(branch ? { default_branch: branch } : {}),
          });
          onStarted(data.scan_id, data.repository_id);
        },
      });
    } else {
      uploadScan(
        { repoName: selectedFolderName || 'uploaded-repo', files: selectedFiles, config },
        { onSuccess: data => onStarted(data.scan_id, data.repository_id) },
      );
    }
  };

  // Called when user clicks "Scan" directly from the tree explorer.
  // Sets the branch then submits immediately with that branch value.
  const handleTreeScan = useCallback((selectedBranchName: string) => {
    setBranch(selectedBranchName);
    setTouched(true);
    const req = {
      source_type: 'github' as const,
      repository_url: inputValue.trim(),
      branch: selectedBranchName,
      config,
    };
    runScan(req, {
      onSuccess: data => {
        saveRecentRepo({
          value: inputValue.trim(),
          source_type: 'github',
          label: inputValue.trim().replace('https://github.com/', '').split('/').slice(0, 2).join('/'),
          last_used: new Date().toISOString(),
          default_branch: selectedBranchName,
        });
        onStarted(data.scan_id, data.repository_id);
      },
    });
  }, [inputValue, config, runScan, onStarted]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
      />

      {/* Modal card */}
      <div className="relative z-10 w-full max-w-lg bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 animate-scale-in overflow-hidden flex flex-col max-h-[90vh]">

        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-slate-100 dark:border-slate-800 shrink-0">
          <div>
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">Run New Scan</h2>
            <p className="text-xs text-slate-500 mt-0.5">Analyze a repository with all five AI agents</p>
          </div>
          <button
            onClick={onClose}
            className="ml-4 shrink-0 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-4">

          {/* ── Source type toggle ── */}
          <div>
            <label className="block text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-2">
              Source
            </label>
            <div className="grid grid-cols-2 gap-1 p-1 rounded-xl bg-slate-100 dark:bg-slate-800">
              {([
                { type: 'github' as const, icon: Globe, label: 'GitHub URL' },
                { type: 'local' as const, icon: Upload, label: 'Upload Folder' },
              ]).map(({ type, icon: Icon, label }) => (
                <button
                  key={type}
                  onClick={() => {
                    setSourceType(type);
                    setInputValue('');
                    setBranch('');
                    setTouched(false);
                    setSelectedFiles([]);
                    setSelectedFolderName('');
                    setGitignoreFilteredCount(0);
                    resetRunMutation();
                    resetUploadMutation();
                  }}
                  className={cn(
                    'flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-200',
                    sourceType === type
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm'
                      : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300',
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* ── Repository input ── */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">
                {sourceType === 'github' ? 'Repository URL' : 'Select Folder or ZIP'}
              </label>
              {sourceType === 'github' && filteredRecent.length > 0 && (
                <button
                  onClick={() => setShowRecent(v => !v)}
                  className="flex items-center gap-1 text-[11px] text-[#ED1D24] hover:text-red-700 transition-colors"
                >
                  <Clock className="h-3 w-3" />
                  Recent
                  <ChevronDown className={cn('h-3 w-3 transition-transform duration-200', showRecent && 'rotate-180')} />
                </button>
              )}
            </div>

            {/* GitHub URL input */}
            {sourceType === 'github' && (
              <div className="relative">
                <Input
                  ref={inputRef}
                  value={inputValue}
                  onChange={e => {
                    const parsed = parseGitHubUrl(e.target.value);
                    setInputValue(parsed.baseUrl);
                    // Auto-populate branch from /tree/{branch} paste; clear otherwise
                    if (parsed.branch) setBranch(parsed.branch);
                    else setBranch('');
                  }}
                  onBlur={() => setTouched(true)}
                  placeholder="https://github.com/owner/repository"
                  className={cn(validationError && 'border-red-400 focus-visible:ring-red-400')}
                  onKeyDown={e => { if (e.key === 'Enter') handleSubmit(); }}
                />
                {branchesFetching && (
                  <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 animate-spin pointer-events-none" />
                )}
              </div>
            )}

            {/* Local folder / ZIP upload */}
            {sourceType === 'local' && (
              <>
                {/* Hidden file inputs */}
                <input
                  ref={folderInputRef}
                  type="file"
                  multiple
                  className="hidden"
                  onChange={handleFolderSelect}
                  {...{ webkitdirectory: '' } as React.InputHTMLAttributes<HTMLInputElement>}
                />
                <input
                  ref={zipInputRef}
                  type="file"
                  accept=".zip"
                  className="hidden"
                  onChange={handleZipSelect}
                />

                {selectedFiles.length === 0 ? (
                  /* Drop zone */
                  <div
                    className={cn(
                      'rounded-xl border-2 border-dashed border-slate-300 dark:border-slate-600 p-5 text-center transition-colors',
                      validationError && 'border-red-400',
                    )}
                  >
                    <Upload className="mx-auto mb-2 h-7 w-7 text-slate-400" />
                    <p className="text-sm font-medium text-slate-600 dark:text-slate-300 mb-0.5">
                      Select your project folder
                    </p>
                    <p className="text-xs text-slate-400 mb-3">
                      Works on Windows, Mac, and Linux — no path access required
                    </p>
                    <div className="flex items-center justify-center gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="gap-1.5 text-xs"
                        onClick={() => folderInputRef.current?.click()}
                      >
                        <FolderOpen className="h-3.5 w-3.5" />
                        Browse Folder
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="gap-1.5 text-xs"
                        onClick={() => zipInputRef.current?.click()}
                      >
                        <FileArchive className="h-3.5 w-3.5" />
                        Upload ZIP
                      </Button>
                    </div>
                  </div>
                ) : uploadPending ? (
                  /* Uploading in-progress state */
                  <div className="rounded-xl border border-[#ED1D24]/40 bg-red-50 dark:bg-red-950/20 px-4 py-3">
                    <div className="flex items-center gap-3 mb-2">
                      <Loader2 className="h-5 w-5 text-[#ED1D24] animate-spin shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
                          Uploading {selectedFolderName}…
                        </p>
                        <p className="text-xs text-slate-400">
                          {selectedFiles.length.toLocaleString()} files · {formatBytes(selectedFiles.reduce((s, f) => s + f.size, 0))}
                        </p>
                      </div>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
                      <div className="h-full rounded-full bg-[#ED1D24] animate-pulse w-2/3" />
                    </div>
                  </div>
                ) : (
                  /* Files selected summary */
                  <div className="rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 px-4 py-3 flex items-center gap-3">
                    <CheckCircle2 className="h-5 w-5 text-emerald-500 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
                        {selectedFolderName}
                      </p>
                      <p className="text-xs text-slate-400">
                        {selectedFiles.length.toLocaleString()} files ·{' '}
                        {formatBytes(selectedFiles.reduce((s, f) => s + f.size, 0))}
                        {gitignoreFilteredCount > 0 && (
                          <span className="ml-1.5 text-amber-500 dark:text-amber-400">
                            · {gitignoreFilteredCount.toLocaleString()} excluded by .gitignore
                          </span>
                        )}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={clearUploadSelection}
                      className="shrink-0 rounded-md p-1 text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 hover:text-slate-600 transition-colors"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </>
            )}

            {validationError && (
              <p className="flex items-center gap-1.5 mt-1.5 text-xs text-red-500 animate-fade-in">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                {validationError}
              </p>
            )}

            {/* Recent repos dropdown (github only) */}
            {sourceType === 'github' && showRecent && filteredRecent.length > 0 && (
              <div className="mt-1 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-xl overflow-hidden animate-scale-in">
                <div className="px-4 py-2 text-[11px] font-semibold uppercase tracking-widest text-slate-400 border-b border-slate-100 dark:border-slate-800">
                  Recent
                </div>
                {filteredRecent.map(repo => (
                  <button
                    key={repo.value}
                    onClick={() => {
                      setInputValue(repo.value);
                      if (repo.default_branch) setBranch(repo.default_branch);
                      setShowRecent(false);
                      setTouched(false);
                      resetRunMutation();
                    }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                  >
                    <Clock className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">{repo.label}</p>
                      <p className="text-[11px] text-slate-400 truncate">{repo.value}</p>
                    </div>
                    <span className="text-[11px] text-slate-400 shrink-0">
                      {new Date(repo.last_used).toLocaleDateString()}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* ── Repository Explorer (tree: branches + PRs) ── */}
          {sourceType === 'github' && isValid && (
            <div className="animate-fade-in">
              <RepoExplorer
                repoUrl={inputValue.trim()}
                selectedBranch={branch}
                onScan={handleTreeScan}
              />
            </div>
          )}

          {/* ── Manual branch input (when URL valid but no explorer yet) ── */}
          {showManualBranch && (
            <div className="animate-fade-in">
              <label className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-2">
                <GitBranch className="h-3 w-3" />
                Branch
                <span className="normal-case font-normal text-slate-400 ml-1">(optional)</span>
              </label>
              <Input
                value={branch}
                onChange={e => setBranch(e.target.value)}
                placeholder="main"
              />
            </div>
          )}

          {/* ── Scan configuration (collapsible) ── */}
          <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
            <button
              onClick={() => setConfigOpen(v => !v)}
              className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-left"
            >
              <div className="flex items-center gap-2 min-w-0">
                <Settings2 className="h-4 w-4 text-slate-400 shrink-0" />
                <span className="text-sm font-medium text-slate-700 dark:text-slate-300">Scan Configuration</span>
                <span className="hidden sm:block text-xs text-slate-400 truncate">
                  {MODES.find(m => m.value === config.mode)?.label ?? 'Standard'}
                  {config.mode !== 'quick' && config.mode !== 'security_only' && ` · ${config.depth}`}
                  {` · ${config.agents.length} agent${config.agents.length !== 1 ? 's' : ''}`}
                </span>
              </div>
              <ChevronRight
                className={cn(
                  'h-4 w-4 text-slate-400 shrink-0 ml-2 transition-transform duration-200',
                  configOpen && 'rotate-90',
                )}
              />
            </button>

            {configOpen && (
              <div className="px-4 py-4 space-y-5 border-t border-slate-200 dark:border-slate-700 animate-fade-in">

                {/* Mode */}
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-2">Mode</p>
                  <div className="grid grid-cols-2 gap-2">
                    {MODES.map(({ value, icon: Icon, label, desc, time }) => {
                      const active = config.mode === value;
                      return (
                        <button
                          key={value}
                          onClick={() => handleModeChange(value)}
                          className={cn(
                            'flex items-start gap-2.5 rounded-xl p-3 border text-left transition-all',
                            active
                              ? 'border-[#ED1D24] bg-red-50 dark:bg-red-950/30 dark:border-red-600'
                              : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600',
                          )}
                        >
                          <Icon className={cn('h-4 w-4 mt-0.5 shrink-0', active ? 'text-[#ED1D24] dark:text-red-400' : 'text-slate-400')} />
                          <div>
                            <p className={cn('text-xs font-semibold', active ? 'text-[#ED1D24] dark:text-red-300' : 'text-slate-700 dark:text-slate-300')}>
                              {label}
                            </p>
                            <p className="text-[11px] text-slate-400">{desc}</p>
                            <p className={cn('text-[11px] mt-0.5', active ? 'text-[#ED1D24] dark:text-red-400' : 'text-slate-400')}>
                              {time}
                            </p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Depth (standard / deep mode only) */}
                {(config.mode === 'standard' || config.mode === 'deep') && (
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-2">Analysis Depth</p>
                    <div className="flex gap-1">
                      {DEPTHS.map((d, i) => {
                        const active = config.depth === d.value;
                        return (
                          <div key={d.value} className="flex items-center flex-1">
                            <button
                              onClick={() => setConfig(c => ({ ...c, depth: d.value }))}
                              className={cn(
                                'flex-1 flex flex-col items-center gap-0.5 py-2 rounded-xl border text-center transition-all',
                                active
                                  ? 'border-[#ED1D24] bg-red-50 dark:bg-red-950/30'
                                  : 'border-slate-200 dark:border-slate-700 hover:border-slate-300',
                              )}
                            >
                              <span className={cn('text-xs font-semibold', active ? 'text-[#ED1D24] dark:text-red-300' : 'text-slate-600 dark:text-slate-400')}>
                                {d.label}
                              </span>
                              <span className="text-[11px] text-slate-400">{d.sub}</span>
                            </button>
                            {i < DEPTHS.length - 1 && (
                              <div className="h-px w-2 bg-slate-200 dark:bg-slate-700 shrink-0" />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Agent toggles */}
                {config.mode !== 'security_only' && (
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-widest text-slate-400 mb-2">
                      Agents
                      {config.mode === 'quick' && (
                        <span className="ml-2 normal-case font-normal text-amber-500">
                          all required for quick mode
                        </span>
                      )}
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {ALL_AGENTS.map(agent => {
                        const active = config.agents.includes(agent);
                        const disabled = config.mode === 'quick';
                        return (
                          <button
                            key={agent}
                            disabled={disabled}
                            onClick={() => toggleAgent(agent)}
                            className={cn(
                              'px-3 py-1 rounded-full text-xs font-medium transition-all border',
                              active
                                ? 'bg-[#ED1D24] border-[#ED1D24] text-white shadow-sm'
                                : 'border-slate-300 dark:border-slate-600 text-slate-500 dark:text-slate-400 hover:border-slate-400 hover:text-slate-600',
                              disabled && 'opacity-60 cursor-not-allowed',
                            )}
                          >
                            {agent}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Operation mode */}
                <ScanModeSelector
                  value={config.operation_mode}
                  onChange={(operation_mode: ScanOperationMode) =>
                    setConfig(c => ({ ...c, operation_mode }))
                  }
                />
              </div>
            )}
          </div>

          {/* API error */}
          {anyError && (
            <div className="flex items-start gap-2 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 px-3 py-2.5 animate-fade-in">
              <AlertCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
              <p className="text-sm text-red-700 dark:text-red-300">{anyError.message}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/20 rounded-b-2xl shrink-0">
          <div className="flex items-center gap-1.5 text-xs text-slate-500 min-w-0">
            <span className="text-base">⏱</span>
            <span>Est.</span>
            <span className="font-semibold text-slate-700 dark:text-slate-300 truncate">
              {estimated.label}
            </span>
            <span className="text-slate-300 dark:text-slate-600">·</span>
            <span>{config.agents.length} agent{config.agents.length !== 1 ? 's' : ''}</span>
          </div>

          <div className="flex gap-2 shrink-0 ml-4">
            <Button variant="outline" size="sm" onClick={onClose} disabled={isPending}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleSubmit}
              disabled={isPending || (touched && !isValid) || config.agents.length === 0}
            >
              {isPending ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Starting…
                </>
              ) : (
                <>
                  <Play className="h-3.5 w-3.5" />
                  Run Scan
                </>
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
