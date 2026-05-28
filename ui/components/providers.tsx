'use client';

import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '@/components/auth/AuthProvider';
import { ScanTriggerModal } from '@/components/scan/ScanTriggerModal';
import { ActiveScanBanner } from '@/components/scan/ActiveScanBanner';

// ─── Scan modal state machine ─────────────────────────────────────────────────

type ScanModalMode = 'trigger' | 'progress' | null;

/** Pre-fill data when opening the scan trigger from a repository detail page. */
export interface RepoPreset {
  /** 'github' or 'local' — controls which tab is shown first */
  sourceType: 'github' | 'local';
  /** GitHub repository URL (only when sourceType is 'github') */
  url?: string;
  /** Human-readable repo name (used for display / upload mode label) */
  name?: string;
}

interface ScanModalState {
  mode: ScanModalMode;
  scanId?: string;
  repositoryId?: string;
  repoPreset?: RepoPreset;
}

interface ScanModalContextValue {
  /** Open the trigger modal with no pre-fill */
  openTrigger: () => void;
  /** Open the trigger modal pre-filled with a specific repository */
  openTriggerWithPreset: (preset: RepoPreset) => void;
  /** Transition from trigger → progress after a scan is queued */
  startProgress: (scanId: string, repositoryId: string) => void;
  /** Close everything */
  close: () => void;
  /** Retry: go back to the trigger modal */
  retry: () => void;
}

const ScanModalContext = createContext<ScanModalContextValue>({
  openTrigger: () => {},
  openTriggerWithPreset: () => {},
  startProgress: () => {},
  close: () => {},
  retry: () => {},
});

export const useScanModal = () => useContext(ScanModalContext);

// ─── QueryClient factory ──────────────────────────────────────────────────────

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 0,
        retry: 1,
        gcTime: 5 * 60 * 1_000,
        refetchOnWindowFocus: false,
        refetchOnMount: true,
      },
    },
  });
}

// ─── Provider ─────────────────────────────────────────────────────────────────

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => makeQueryClient());
  const [state, setState] = useState<ScanModalState>({ mode: null });

  const ctx: ScanModalContextValue = {
    openTrigger: () => setState({ mode: 'trigger' }),
    openTriggerWithPreset: (preset) => setState({ mode: 'trigger', repoPreset: preset }),
    startProgress: (scanId, repositoryId) =>
      setState({ mode: 'progress', scanId, repositoryId }),
    close: () => setState({ mode: null }),
    retry: () => setState((prev) => ({ mode: 'trigger', repoPreset: prev.repoPreset })),
  };

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ScanModalContext.Provider value={ctx}>
          {children}

          {state.mode === 'trigger' && (
            <ScanTriggerModal
              open
              onClose={ctx.close}
              onStarted={ctx.startProgress}
              initialPreset={state.repoPreset}
            />
          )}

          {state.mode === 'progress' && state.scanId && state.repositoryId && (
            <ActiveScanBanner
              scanId={state.scanId}
              repositoryId={state.repositoryId}
              onClose={ctx.close}
              onRetry={ctx.retry}
            />
          )}
        </ScanModalContext.Provider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
