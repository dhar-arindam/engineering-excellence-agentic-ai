'use client';

import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import {
  X, FileCode, Minus, Plus, ChevronRight, ChevronDown,
  Folder, FolderOpen, MessageSquare, AlertTriangle, Info,
  Columns2, AlignLeft,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePatch } from '@/hooks/usePatch';
import { usePatchAnnotations } from '@/hooks/usePatchAnnotations';
import { Button } from '@/components/ui/button';
import type { PatchAnnotations, FileAnnotation, HunkAnnotation, ImpactLevel } from '@/types';

// ─── Internal types ───────────────────────────────────────────────────────────

type DiffViewMode = 'unified' | 'split';
type LineType = 'added' | 'removed' | 'context' | 'meta';

interface DiffLine {
  type: LineType;
  content: string;
  oldLineNo?: number;
  newLineNo?: number;
}

interface ParsedHunk {
  header: string;
  oldStart: number;
  newStart: number;
  lines: DiffLine[];
  annotation?: HunkAnnotation;
}

interface ParsedFile {
  file: string;
  hunks: ParsedHunk[];
  addedCount: number;
  removedCount: number;
  annotation?: FileAnnotation;
}

interface TreeNode {
  name: string;
  path: string;
  isFile: boolean;
  children: TreeNode[];
  fileIndex?: number;
}

interface SplitSide {
  type: 'removed' | 'added' | 'context' | 'empty';
  content: string;
  lineNo?: number;
}

interface SplitRow {
  left: SplitSide;
  right: SplitSide;
}

// ─── Diff parser ──────────────────────────────────────────────────────────────

function parseHunkHeader(line: string): { oldStart: number; newStart: number } {
  const m = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  return m
    ? { oldStart: parseInt(m[1], 10), newStart: parseInt(m[2], 10) }
    : { oldStart: 1, newStart: 1 };
}

function parseDiff(raw: string, annotations?: PatchAnnotations): ParsedFile[] {
  const files: ParsedFile[] = [];
  let currentFile: ParsedFile | null = null;
  let currentHunk: ParsedHunk | null = null;
  let oldLineNo = 0;
  let newLineNo = 0;

  const annotationMap = new Map<string, FileAnnotation>(
    (annotations?.files ?? []).map(fa => [fa.file, fa]),
  );

  for (const rawLine of raw.split('\n')) {
    if (rawLine.startsWith('+++ b/')) {
      const file = rawLine.slice(6);
      currentFile = { file, hunks: [], addedCount: 0, removedCount: 0, annotation: annotationMap.get(file) };
      files.push(currentFile);
      currentHunk = null;
      continue;
    }
    if (rawLine.startsWith('--- ') || rawLine.startsWith('diff ') || rawLine.startsWith('index ')) continue;
    if (!currentFile) continue;

    if (rawLine.startsWith('@@')) {
      const { oldStart, newStart } = parseHunkHeader(rawLine);
      oldLineNo = oldStart;
      newLineNo = newStart;
      const hunkIdx = currentFile.hunks.length;
      const ha = currentFile.annotation?.hunks.find(h => h.hunk_index === hunkIdx);
      currentHunk = { header: rawLine, oldStart, newStart, lines: [], annotation: ha };
      currentFile.hunks.push(currentHunk);
      continue;
    }
    if (!currentHunk) continue;

    if (rawLine.startsWith('+')) {
      currentHunk.lines.push({ type: 'added',   content: rawLine.slice(1), newLineNo: newLineNo++ });
      currentFile.addedCount++;
    } else if (rawLine.startsWith('-')) {
      currentHunk.lines.push({ type: 'removed', content: rawLine.slice(1), oldLineNo: oldLineNo++ });
      currentFile.removedCount++;
    } else if (rawLine.startsWith('\\')) {
      currentHunk.lines.push({ type: 'meta', content: rawLine });
    } else {
      currentHunk.lines.push({
        type: 'context',
        content: rawLine.startsWith(' ') ? rawLine.slice(1) : rawLine,
        oldLineNo: oldLineNo++,
        newLineNo: newLineNo++,
      });
    }
  }
  return files;
}

// ─── Split-view row builder ───────────────────────────────────────────────────

function buildSplitRows(lines: DiffLine[]): SplitRow[] {
  const rows: SplitRow[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.type === 'meta') { i++; continue; }

    if (line.type === 'removed') {
      const removed: DiffLine[] = [];
      while (i < lines.length && lines[i].type === 'removed') removed.push(lines[i++]);
      const added: DiffLine[] = [];
      while (i < lines.length && lines[i].type === 'added')   added.push(lines[i++]);
      const max = Math.max(removed.length, added.length);
      for (let j = 0; j < max; j++) {
        const rem = removed[j];
        const add = added[j];
        rows.push({
          left:  rem ? { type: 'removed', content: rem.content, lineNo: rem.oldLineNo } : { type: 'empty', content: '' },
          right: add ? { type: 'added',   content: add.content, lineNo: add.newLineNo } : { type: 'empty', content: '' },
        });
      }
    } else if (line.type === 'added') {
      rows.push({ left: { type: 'empty', content: '' }, right: { type: 'added', content: line.content, lineNo: line.newLineNo } });
      i++;
    } else {
      rows.push({
        left:  { type: 'context', content: line.content, lineNo: line.oldLineNo },
        right: { type: 'context', content: line.content, lineNo: line.newLineNo },
      });
      i++;
    }
  }
  return rows;
}

// ─── File tree builder ────────────────────────────────────────────────────────

function buildFileTree(files: ParsedFile[]): TreeNode {
  const root: TreeNode = { name: '', path: '', isFile: false, children: [] };
  for (let fi = 0; fi < files.length; fi++) {
    const parts = files[fi].file.split('/');
    let node = root;
    for (let pi = 0; pi < parts.length; pi++) {
      const name   = parts[pi];
      const path   = parts.slice(0, pi + 1).join('/');
      const isFile = pi === parts.length - 1;
      let child = node.children.find(c => c.name === name);
      if (!child) {
        child = { name, path, isFile, children: [] };
        if (isFile) child.fileIndex = fi;
        node.children.push(child);
      }
      node = child;
    }
  }
  return root;
}

// ─── Visual helpers ───────────────────────────────────────────────────────────

const impactBg: Record<ImpactLevel, string> = {
  Low:    'bg-amber-100  text-amber-700  dark:bg-amber-900/40  dark:text-amber-300',
  Medium: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  High:   'bg-red-100   text-red-700   dark:bg-red-900/40   dark:text-red-300',
};

const riskFill: Record<'Low' | 'Medium' | 'High' | 'Critical', string> = {
  Low:      'bg-emerald-400',
  Medium:   'bg-amber-400',
  High:     'bg-red-500',
  Critical: 'bg-red-700',
};

function riskLevelFromScore(score: number): 'Low' | 'Medium' | 'High' | 'Critical' {
  return score >= 9 ? 'Critical' : score >= 7 ? 'High' : score >= 4 ? 'Medium' : 'Low';
}

function ImpactBadge({ level }: { level: ImpactLevel }) {
  return (
    <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide', impactBg[level])}>
      {level}
    </span>
  );
}

function RiskBar({ score, level }: { score: number; level: 'Low' | 'Medium' | 'High' | 'Critical' }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="flex gap-[2px]" aria-label={`Risk ${score} of 10`}>
        {Array.from({ length: 10 }, (_, i) => (
          <span key={i} className={cn('h-[7px] w-[5px] rounded-[1px]', i < score ? riskFill[level] : 'bg-slate-200 dark:bg-slate-700')} />
        ))}
      </span>
      <span className="text-[11px] font-mono text-slate-500 dark:text-slate-400">{score}/10</span>
      <span className={cn('text-[10px] font-semibold',
        level === 'Low' ? 'text-emerald-600 dark:text-emerald-400' :
        level === 'Medium' ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400')}>
        {level}
      </span>
    </span>
  );
}

// ─── Hunk annotation card ─────────────────────────────────────────────────────

function HunkAnnotationCard({ annotation }: { annotation: HunkAnnotation }) {
  const [expanded, setExpanded] = useState(true);
  const borderColor =
    annotation.risk_level === 'High'   ? 'border-red-400 dark:border-red-600' :
    annotation.risk_level === 'Medium' ? 'border-amber-400 dark:border-amber-600' :
                                        'border-emerald-400 dark:border-emerald-600';

  return (
    <div className={cn('border-l-[3px] bg-slate-50 dark:bg-slate-800/60 text-xs', borderColor)}>
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors text-left"
      >
        <MessageSquare className="h-3 w-3 text-slate-400 shrink-0" />
        <span className="flex-1 font-medium text-slate-600 dark:text-slate-400">Why this change?</span>
        <span className="flex items-center gap-1.5 shrink-0">
          <ImpactBadge level={annotation.impact} />
          {expanded
            ? <ChevronDown  className="h-3 w-3 text-slate-400" />
            : <ChevronRight className="h-3 w-3 text-slate-400" />}
        </span>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2.5">
          <p className="text-slate-700 dark:text-slate-300 leading-relaxed">{annotation.reason}</p>
          <div className="flex items-center gap-3 flex-wrap">
            <span className="flex items-center gap-1.5 text-slate-500 dark:text-slate-400">
              <AlertTriangle className="h-3 w-3 shrink-0" />
              Risk:
              <RiskBar score={annotation.risk_score} level={annotation.risk_level} />
            </span>
            {annotation.references && annotation.references.length > 0 && (
              <span className="flex items-center gap-1 flex-wrap">
                {annotation.references.map(ref => (
                  <span key={ref} className="px-1.5 py-0.5 bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400 rounded text-[10px] font-mono">
                    {ref}
                  </span>
                ))}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Shared line-number cell ──────────────────────────────────────────────────

function LineNo({ n, bg }: { n?: number; bg?: string }) {
  return (
    <td className={cn(
      'w-10 min-w-[2.5rem] select-none px-2 text-right text-[10px] font-mono text-slate-400 dark:text-slate-600 border-r border-slate-200 dark:border-slate-700 align-top',
      bg,
    )}>
      {n ?? ''}
    </td>
  );
}

// ─── Unified diff hunk table ──────────────────────────────────────────────────

function UnifiedHunkTable({ lines }: { lines: DiffLine[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => {
            if (line.type === 'meta') return null;
            const rowBg =
              line.type === 'added'   ? 'bg-emerald-50/80 dark:bg-emerald-950/30' :
              line.type === 'removed' ? 'bg-red-50/80 dark:bg-red-950/30' : '';
            return (
              <tr key={i} className={rowBg}>
                <LineNo n={line.oldLineNo} bg={rowBg} />
                <LineNo n={line.newLineNo} bg={rowBg} />
                <td className="w-5 select-none text-center align-top px-1 py-[1px]">
                  {line.type === 'added'   ? <Plus  className="h-2.5 w-2.5 text-emerald-500 mx-auto mt-[3px]" /> :
                   line.type === 'removed' ? <Minus className="h-2.5 w-2.5 text-red-500 mx-auto mt-[3px]" /> : null}
                </td>
                <td className={cn(
                  'py-[1px] pl-1 pr-4 font-mono text-[12px] whitespace-pre align-top leading-5',
                  line.type === 'added'   ? 'text-emerald-800 dark:text-emerald-200' :
                  line.type === 'removed' ? 'text-red-800 dark:text-red-200' :
                                            'text-slate-700 dark:text-slate-300',
                )}>
                  {line.content || ' '}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Split diff hunk table ────────────────────────────────────────────────────

const splitBg: Record<SplitSide['type'], string> = {
  added:   'bg-emerald-50/80 dark:bg-emerald-950/30',
  removed: 'bg-red-50/80 dark:bg-red-950/30',
  context: '',
  empty:   'bg-slate-50/60 dark:bg-slate-800/20',
};
const splitText: Record<SplitSide['type'], string> = {
  added:   'text-emerald-800 dark:text-emerald-200',
  removed: 'text-red-800 dark:text-red-200',
  context: 'text-slate-700 dark:text-slate-300',
  empty:   '',
};

function SplitHunkTable({ lines }: { lines: DiffLine[] }) {
  const rows = useMemo(() => buildSplitRows(lines), [lines]);
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse table-fixed">
        <colgroup>
          <col className="w-10" />
          <col className="w-[calc(50%-1.25rem)]" />
          <col className="w-10" />
          <col className="w-[calc(50%-1.25rem)]" />
        </colgroup>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <LineNo n={row.left.lineNo}  bg={splitBg[row.left.type]} />
              <td className={cn('py-[1px] pl-1 pr-2 font-mono text-[12px] whitespace-pre align-top leading-5 border-r border-slate-200 dark:border-slate-700', splitBg[row.left.type], splitText[row.left.type])}>
                {row.left.content || ' '}
              </td>
              <LineNo n={row.right.lineNo} bg={splitBg[row.right.type]} />
              <td className={cn('py-[1px] pl-1 pr-2 font-mono text-[12px] whitespace-pre align-top leading-5', splitBg[row.right.type], splitText[row.right.type])}>
                {row.right.content || ' '}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Hunk block ───────────────────────────────────────────────────────────────

function HunkBlock({ hunk, viewMode }: { hunk: ParsedHunk; viewMode: DiffViewMode }) {
  const [open, setOpen] = useState(true);
  const context = hunk.header.match(/@@ .+ @@(.*)/)?.[1]?.trim() ?? '';

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 px-3 py-1.5 bg-red-50/60 dark:bg-red-950/20 hover:bg-red-100/60 dark:hover:bg-red-950/30 transition-colors text-left border-b border-slate-200 dark:border-slate-700"
      >
        <span className="font-mono text-[11px] text-[#ED1D24] dark:text-red-400 shrink-0 select-none">
          @@ -{hunk.oldStart} +{hunk.newStart} @@
        </span>
        {context && <span className="font-mono text-[11px] text-slate-500 dark:text-slate-500 truncate">{context}</span>}
        <ChevronDown className={cn('h-3 w-3 text-slate-400 ml-auto shrink-0 transition-transform duration-150', !open && '-rotate-90')} />
      </button>

      {open && (
        <>
          {hunk.annotation && <HunkAnnotationCard annotation={hunk.annotation} />}
          {viewMode === 'unified'
            ? <UnifiedHunkTable lines={hunk.lines} />
            : <SplitHunkTable   lines={hunk.lines} />}
        </>
      )}
    </div>
  );
}

// ─── File diff block ──────────────────────────────────────────────────────────

interface FileDiffBlockProps {
  file: ParsedFile;
  index: number;
  viewMode: DiffViewMode;
  isSelected: boolean;
  onRegisterRef: (index: number, el: HTMLElement | null) => void;
}

function FileDiffBlock({ file, index, viewMode, isSelected, onRegisterRef }: FileDiffBlockProps) {
  const [open, setOpen] = useState(true);
  const ann = file.annotation;
  const level = ann ? riskLevelFromScore(ann.risk_score) : undefined;

  const setRef = useCallback((el: HTMLElement | null) => {
    onRegisterRef(index, el);
  }, [index, onRegisterRef]);

  return (
    <div
      ref={setRef}
      className={cn(
        'rounded-xl border overflow-hidden transition-all duration-200',
        isSelected
          ? 'border-[#ED1D24] dark:border-red-600 shadow-md shadow-red-500/10'
          : 'border-slate-200 dark:border-slate-700',
      )}
    >
      {/* File header */}
      <div className="flex items-center gap-2 px-3 py-2.5 bg-slate-50 dark:bg-slate-800/80 border-b border-slate-200 dark:border-slate-700">
        <button
          onClick={() => setOpen(v => !v)}
          className="flex items-center gap-2 flex-1 min-w-0 text-left group"
        >
          <FileCode className="h-3.5 w-3.5 text-slate-400 shrink-0" />
          <span className="font-mono text-xs text-slate-700 dark:text-slate-300 truncate flex-1 group-hover:text-slate-900 dark:group-hover:text-slate-100 transition-colors">
            {file.file}
          </span>
          <ChevronDown className={cn('h-3.5 w-3.5 text-slate-400 shrink-0 transition-transform duration-150', !open && '-rotate-90')} />
        </button>

        <div className="flex items-center gap-2 shrink-0 pl-2 border-l border-slate-200 dark:border-slate-700">
          <span className="text-[11px] font-mono font-semibold text-emerald-600 dark:text-emerald-400">+{file.addedCount}</span>
          <span className="text-[11px] font-mono font-semibold text-red-600 dark:text-red-400">-{file.removedCount}</span>
          {ann && level && (
            <>
              <RiskBar score={ann.risk_score} level={level} />
              <ImpactBadge level={ann.impact} />
            </>
          )}
        </div>
      </div>

      {open && (
        <div className="divide-y divide-slate-100 dark:divide-slate-800 bg-white dark:bg-slate-900">
          {file.hunks.map((hunk, hi) => (
            <HunkBlock key={hi} hunk={hunk} viewMode={viewMode} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── File tree ────────────────────────────────────────────────────────────────

interface TreeNodeItemProps {
  node: TreeNode;
  files: ParsedFile[];
  selectedIndex: number;
  onSelect: (i: number) => void;
  depth: number;
}

function TreeNodeItem({ node, files, selectedIndex, onSelect, depth }: TreeNodeItemProps) {
  const [expanded, setExpanded] = useState(true);
  const indent = 8 + depth * 14;

  if (node.isFile && node.fileIndex !== undefined) {
    const file = files[node.fileIndex];
    const ann  = file.annotation;
    const level = ann ? riskLevelFromScore(ann.risk_score) : null;
    const dotColor =
      level === 'High' ? 'bg-red-400' : level === 'Medium' ? 'bg-amber-400' : 'bg-emerald-400';
    const active = selectedIndex === node.fileIndex;

    return (
      <button
        onClick={() => onSelect(node.fileIndex!)}
        style={{ paddingLeft: `${indent}px` }}
        className={cn(
          'w-full flex items-center gap-1.5 pr-2 py-1.5 rounded-md text-left text-xs transition-colors',
          active
            ? 'bg-red-100 dark:bg-red-900/40 text-[#ED1D24] dark:text-red-300'
            : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800',
        )}
      >
        <span className={cn('h-2 w-2 rounded-full shrink-0', dotColor)} />
        <span className="flex-1 truncate font-mono">{node.name}</span>
        {ann && <ImpactBadge level={ann.impact} />}
      </button>
    );
  }

  return (
    <div>
      <button
        onClick={() => setExpanded(v => !v)}
        style={{ paddingLeft: `${indent}px` }}
        className="w-full flex items-center gap-1.5 pr-2 py-1 rounded-md text-left text-xs text-slate-500 dark:text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        {expanded
          ? <FolderOpen className="h-3.5 w-3.5 text-amber-400 shrink-0" />
          : <Folder     className="h-3.5 w-3.5 text-amber-400 shrink-0" />}
        <span className="flex-1 truncate">{node.name}/</span>
        <ChevronDown className={cn('h-3 w-3 text-slate-400 transition-transform duration-150', !expanded && '-rotate-90')} />
      </button>
      {expanded && node.children.map(child => (
        <TreeNodeItem key={child.path} node={child} files={files} selectedIndex={selectedIndex} onSelect={onSelect} depth={depth + 1} />
      ))}
    </div>
  );
}

function FileTreeSidebar({ files, selectedIndex, onSelect }: { files: ParsedFile[]; selectedIndex: number; onSelect: (i: number) => void }) {
  const tree = useMemo(() => buildFileTree(files), [files]);
  const totalAdded   = files.reduce((s, f) => s + f.addedCount,   0);
  const totalRemoved = files.reduce((s, f) => s + f.removedCount, 0);

  return (
    <div className="flex flex-col w-64 shrink-0 border-r border-slate-200 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-800/30">
      <div className="px-3 py-2.5 border-b border-slate-200 dark:border-slate-700 shrink-0">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mb-1.5">Files Changed</p>
        <div className="flex items-center gap-2 text-[11px]">
          <span className="font-semibold text-slate-600 dark:text-slate-400">{files.length} file{files.length !== 1 ? 's' : ''}</span>
          <span className="font-mono font-semibold text-emerald-600 dark:text-emerald-400">+{totalAdded}</span>
          <span className="font-mono font-semibold text-red-600 dark:text-red-400">-{totalRemoved}</span>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto py-1.5 px-1.5 space-y-0.5">
        {tree.children.map(node => (
          <TreeNodeItem key={node.path} node={node} files={files} selectedIndex={selectedIndex} onSelect={onSelect} depth={0} />
        ))}
      </div>
    </div>
  );
}

// ─── View-mode toggle ─────────────────────────────────────────────────────────

function ViewModeToggle({ mode, onChange }: { mode: DiffViewMode; onChange: (m: DiffViewMode) => void }) {
  const opts = [
    { value: 'unified' as const, icon: AlignLeft, label: 'Unified' },
    { value: 'split'   as const, icon: Columns2,  label: 'Split'   },
  ] as const;

  return (
    <div className="flex p-0.5 gap-0.5 bg-slate-100 dark:bg-slate-800 rounded-lg">
      {opts.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          onClick={() => onChange(value)}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all',
            mode === value
              ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm'
              : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300',
          )}
        >
          <Icon className="h-3 w-3" />
          {label}
        </button>
      ))}
    </div>
  );
}

// ─── Modal ────────────────────────────────────────────────────────────────────

export interface PatchPreviewModalProps {
  scanId: string;
  open: boolean;
  onClose: () => void;
}

export function PatchPreviewModal({ scanId, open, onClose }: PatchPreviewModalProps) {
  const [viewMode, setViewMode] = useState<DiffViewMode>('unified');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const scrollRef  = useRef<HTMLDivElement>(null);
  const fileRefMap = useRef<Map<number, HTMLElement>>(new Map());

  const { data: patchText, isLoading, isError, error } = usePatch(scanId, open);
  const { data: annotations } = usePatchAnnotations(scanId, open);

  const files = useMemo(
    () => (patchText ? parseDiff(patchText, annotations) : []),
    [patchText, annotations],
  );

  const overallImpact: ImpactLevel = annotations?.overall_impact ?? (
    files.some(f => f.annotation?.impact === 'High')   ? 'High'   :
    files.some(f => f.annotation?.impact === 'Medium') ? 'Medium' : 'Low'
  );

  const totalAdded   = files.reduce((s, f) => s + f.addedCount,   0);
  const totalRemoved = files.reduce((s, f) => s + f.removedCount, 0);

  const registerRef = useCallback((index: number, el: HTMLElement | null) => {
    if (el) fileRefMap.current.set(index, el);
    else    fileRefMap.current.delete(index);
  }, []);

  const scrollToFile = useCallback((index: number) => {
    setSelectedIndex(index);
    const panel = scrollRef.current;
    const el    = fileRefMap.current.get(index);
    if (!panel || !el) return;
    const panelTop = panel.getBoundingClientRect().top;
    const elTop    = el.getBoundingClientRect().top;
    panel.scrollTo({ top: elTop - panelTop + panel.scrollTop - 8, behavior: 'smooth' });
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm animate-fade-in" onClick={onClose} />

      {/* Modal */}
      <div
        className="relative z-10 w-full max-w-5xl bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-slate-200 dark:border-slate-700 animate-scale-in flex flex-col"
        style={{ height: 'min(90vh, 800px)' }}
      >
        {/* ── Header ── */}
        <div className="flex items-center gap-3 px-5 py-3.5 border-b border-slate-100 dark:border-slate-800 shrink-0">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Suggested Changes</h2>
              {!isLoading && !isError && files.length > 0 && (
                <>
                  <span className="text-xs text-slate-400">{files.length} file{files.length !== 1 ? 's' : ''}</span>
                  <span className="text-xs font-mono font-semibold text-emerald-600 dark:text-emerald-400">+{totalAdded}</span>
                  <span className="text-xs font-mono font-semibold text-red-600 dark:text-red-400">-{totalRemoved}</span>
                  <span className="hidden sm:flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
                    <Info className="h-3 w-3 shrink-0" />
                    Estimated impact: <ImpactBadge level={overallImpact} />
                  </span>
                </>
              )}
            </div>
          </div>

          {files.length > 0 && (
            <ViewModeToggle mode={viewMode} onChange={setViewMode} />
          )}

          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-300 transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* ── Body ── */}
        <div className="flex flex-1 min-h-0">
          {/* File tree sidebar */}
          {files.length > 1 && (
            <FileTreeSidebar files={files} selectedIndex={selectedIndex} onSelect={scrollToFile} />
          )}

          {/* Diff content */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 min-w-0">
            {isLoading && (
              <div className="flex items-center justify-center py-16">
                <div className="h-6 w-6 border-2 border-[#ED1D24] border-t-transparent rounded-full animate-spin" />
              </div>
            )}
            {isError && (
              <div className="rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
                Failed to load patch: {error?.message ?? 'Unknown error'}
              </div>
            )}
            {!isLoading && !isError && files.length === 0 && (
              <p className="text-sm text-slate-500 text-center py-10">No patch content available.</p>
            )}
            {files.map((f, i) => (
              <FileDiffBlock
                key={f.file}
                file={f}
                index={i}
                viewMode={viewMode}
                isSelected={selectedIndex === i}
                onRegisterRef={registerRef}
              />
            ))}
          </div>
        </div>

        {/* ── Footer ── */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/20 rounded-b-2xl shrink-0">
          <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 flex-wrap">
            {files.length > 0 && (
              <span className="flex items-center gap-1">
                <span>Overall estimated impact:</span>
                <ImpactBadge level={overallImpact} />
              </span>
            )}
            {annotations && (
              <span className="hidden sm:block text-slate-400 dark:text-slate-500">
                {files.length} modification{files.length !== 1 ? 's' : ''} annotated
              </span>
            )}
          </div>
          <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>
  );
}

