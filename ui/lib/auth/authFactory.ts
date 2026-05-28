import type { AuthStrategy } from './AuthStrategy';

// ─── Auth mode ────────────────────────────────────────────────────────────────

export type AuthMode = 'local' | 'azure';

export function getAuthMode(): AuthMode {
  const mode = process.env.NEXT_PUBLIC_AUTH_MODE ?? 'local';
  return mode === 'azure' ? 'azure' : 'local';
}

// ─── Singleton instance ───────────────────────────────────────────────────────

let instance: AuthStrategy | null = null;

/**
 * Returns the singleton AuthStrategy for the current environment.
 *
 * The strategy is determined at build time by NEXT_PUBLIC_AUTH_MODE:
 *   local  → LocalAuthStrategy (no MSAL, fallback identity)
 *   azure  → AzureAuthStrategy (MSAL, requires @msal/browser + env vars)
 *
 * The singleton is reset between hot-reloads in development (module cache is
 * cleared), which is the correct behaviour.
 */
export function createAuthStrategy(): AuthStrategy {
  if (instance) return instance;

  if (getAuthMode() === 'azure') {
    // Loaded conditionally so MSAL is tree-shaken in local builds
    const { AzureAuthStrategy } = require('./AzureAuthStrategy') as typeof import('./AzureAuthStrategy');
    instance = new AzureAuthStrategy();
  } else {
    const { LocalAuthStrategy } = require('./LocalAuthStrategy') as typeof import('./LocalAuthStrategy');
    instance = new LocalAuthStrategy();
  }

  return instance!;
}

/** Reset the singleton — useful in tests and HMR. */
export function resetAuthStrategy(): void {
  instance = null;
}
