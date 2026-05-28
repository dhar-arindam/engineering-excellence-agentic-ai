// ─── Auth domain types ────────────────────────────────────────────────────────

export interface AuthUser {
  name: string;
  email: string;
  id: string;
  roles?: string[];
}

// ─── Strategy interface ───────────────────────────────────────────────────────

/**
 * Pluggable authentication strategy.
 *
 * Implementations:
 *  - LocalAuthStrategy  — no-op auth for local development
 *  - AzureAuthStrategy  — MSAL-based Azure AD authentication for production
 */
export interface AuthStrategy {
  /** Resolve the currently signed-in user, or null if not authenticated. */
  getUser(): Promise<AuthUser | null>;

  /**
   * Return a Bearer token to attach to API requests.
   * Returns null in local mode (no token needed).
   */
  getAccessToken(): Promise<string | null>;

  /** Initiate the sign-in flow. */
  login(): Promise<void>;

  /** Initiate the sign-out flow and clear local state. */
  logout(): Promise<void>;
}
