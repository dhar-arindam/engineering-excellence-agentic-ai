'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { createAuthStrategy, getAuthMode, type AuthMode } from '@/lib/auth/authFactory';
import type { AuthUser } from '@/lib/auth/AuthStrategy';
import type { AuthStrategy } from '@/lib/auth/AuthStrategy';

// ─── Context shape ────────────────────────────────────────────────────────────

export interface AuthContextValue {
  /** Currently authenticated user, or null if not signed in / still loading. */
  user: AuthUser | null;
  /** True while the initial identity resolution is in-flight. */
  isLoading: boolean;
  /** Which auth mode is active. Exposed for DEV badge, conditional UI, etc. */
  mode: AuthMode;
  /** Returns a Bearer token (Azure mode) or null (local mode). */
  getAccessToken: () => Promise<string | null>;
  /** Initiates sign-in. No-op in local mode. */
  login: () => Promise<void>;
  /** Initiates sign-out and clears the user from state. */
  logout: () => Promise<void>;
}

// ─── Context ──────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null);

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth() must be called inside <AuthProvider>');
  return ctx;
}

// ─── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser]       = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Stable singleton — safe to reference outside effects
  const strategy: AuthStrategy = createAuthStrategy();
  const mode = getAuthMode();

  // Resolve initial identity on mount
  useEffect(() => {
    let cancelled = false;

    strategy.getUser()
      .then((u) => { if (!cancelled) setUser(u); })
      .catch(() => { /* strategy already handles errors */ })
      .finally(() => { if (!cancelled) setIsLoading(false); });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const getAccessToken = useCallback(
    () => strategy.getAccessToken(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const login = useCallback(
    () => strategy.login(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const logout = useCallback(async () => {
    await strategy.logout();
    setUser(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, mode, getAccessToken, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
