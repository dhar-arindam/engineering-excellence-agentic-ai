import type { AuthStrategy, AuthUser } from './AuthStrategy';

// ─── Fallback identity for when the backend is unavailable ───────────────────

const FALLBACK_USER: AuthUser = {
  name: 'Local Developer',
  email: 'dev@localhost',
  id: 'local-dev',
  roles: ['developer'],
};

// ─── Implementation ───────────────────────────────────────────────────────────

/**
 * LocalAuthStrategy — used when NEXT_PUBLIC_AUTH_MODE=local.
 *
 * Attempts to fetch a real identity from the backend's /api/auth/local-user
 * endpoint (which returns the OS username). Falls back to a hardcoded developer
 * identity if that endpoint is unavailable, so the app always boots cleanly.
 *
 * login() and logout() are deliberate no-ops.
 */
export class LocalAuthStrategy implements AuthStrategy {
  async getUser(): Promise<AuthUser | null> {
    try {
      const res = await fetch('/api/auth/local-user', {
        // Short timeout — backend may not be running
        signal: AbortSignal.timeout(2_000),
      });
      if (!res.ok) return FALLBACK_USER;
      const data = (await res.json()) as Partial<AuthUser>;
      return {
        name:  data.name  ?? FALLBACK_USER.name,
        email: data.email ?? FALLBACK_USER.email,
        id:    data.id    ?? FALLBACK_USER.id,
        roles: data.roles ?? FALLBACK_USER.roles,
      };
    } catch {
      // Backend offline — graceful fallback
      return FALLBACK_USER;
    }
  }

  async getAccessToken(): Promise<string | null> {
    return null;
  }

  async login(): Promise<void> {
    // No-op in local mode
  }

  async logout(): Promise<void> {
    // No-op in local mode
  }
}
