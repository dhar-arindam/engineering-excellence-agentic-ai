import type { AuthStrategy, AuthUser } from './AuthStrategy';

// ─── Minimal MSAL type stubs ──────────────────────────────────────────────────
//
// These mirror the public surface of @msal/browser that this strategy uses.
// They allow the file to compile without the package installed at build time.
// When @msal/browser IS installed (production), the runtime `require()` below
// provides the real implementation — these types are erased by TypeScript.
//
// To install: npm install @msal/browser

interface MsalAccountInfo {
  name?: string;
  username: string;
  localAccountId: string;
  idTokenClaims?: Record<string, unknown>;
}

interface MsalTokenResult {
  accessToken: string;
}

interface MsalPublicClientApp {
  initialize(): Promise<void>;
  handleRedirectPromise(): Promise<unknown>;
  getAllAccounts(): MsalAccountInfo[];
  acquireTokenSilent(request: object): Promise<MsalTokenResult>;
  acquireTokenPopup(request: object): Promise<MsalTokenResult>;
  loginRedirect(request: object): Promise<void>;
  logoutRedirect(request?: object): Promise<void>;
}

// ─── MSAL config (read from build-time env vars) ──────────────────────────────

function buildMsalConfig() {
  return {
    auth: {
      clientId:   process.env.NEXT_PUBLIC_AZURE_CLIENT_ID   ?? '',
      authority:  `https://login.microsoftonline.com/${process.env.NEXT_PUBLIC_AZURE_TENANT_ID ?? 'common'}`,
      redirectUri: typeof window !== 'undefined' ? window.location.origin : '/',
    },
    cache: {
      cacheLocation:    'sessionStorage' as const,
      storeAuthStateInCookie: false,
    },
  };
}

const SCOPES = (process.env.NEXT_PUBLIC_AZURE_SCOPES ?? 'User.Read')
  .split(',')
  .map((s) => s.trim());

// ─── Implementation ───────────────────────────────────────────────────────────

/**
 * AzureAuthStrategy — used when NEXT_PUBLIC_AUTH_MODE=azure.
 *
 * Wraps @msal/browser's PublicClientApplication to provide a clean, framework-
 * agnostic auth strategy. MSAL is loaded via require() at runtime so that:
 *  a) This file compiles without @msal/browser installed (local dev mode).
 *  b) MSAL is tree-shaken from bundles where LOCAL mode is selected at build time.
 *
 * Required env vars:
 *   NEXT_PUBLIC_AZURE_CLIENT_ID   — Azure AD Application (client) ID
 *   NEXT_PUBLIC_AZURE_TENANT_ID   — Azure AD Directory (tenant) ID
 *   NEXT_PUBLIC_AZURE_SCOPES      — Comma-separated scopes (default: User.Read)
 */
export class AzureAuthStrategy implements AuthStrategy {
  private app: MsalPublicClientApp | null = null;
  private initPromise: Promise<void> | null = null;

  private async ensureInit(): Promise<MsalPublicClientApp> {
    if (this.app && this.initPromise) {
      await this.initPromise;
      return this.app;
    }

    // Lazy-load @azure/msal-browser so local-mode bundles never include it
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const msal = require('@azure/msal-browser') as {
      PublicClientApplication: new (config: object) => MsalPublicClientApp;
    };

    this.app = new msal.PublicClientApplication(buildMsalConfig());

    this.initPromise = (async () => {
      await this.app!.initialize();
      await this.app!.handleRedirectPromise();
    })();

    await this.initPromise;
    return this.app;
  }

  async getUser(): Promise<AuthUser | null> {
    const app = await this.ensureInit();
    const accounts = app.getAllAccounts();
    if (!accounts.length) return null;

    const account = accounts[0];
    const claims = account.idTokenClaims;
    return {
      name:  account.name ?? account.username,
      email: account.username,
      id:    account.localAccountId,
      roles: Array.isArray(claims?.roles)
        ? (claims.roles as string[])
        : undefined,
    };
  }

  async getAccessToken(): Promise<string | null> {
    const app = await this.ensureInit();
    const accounts = app.getAllAccounts();
    if (!accounts.length) return null;

    try {
      const result = await app.acquireTokenSilent({
        scopes:  SCOPES,
        account: accounts[0],
      });
      return result.accessToken;
    } catch {
      // Silent acquisition failed — attempt interactive popup
      try {
        const result = await app.acquireTokenPopup({ scopes: SCOPES });
        return result.accessToken;
      } catch {
        return null;
      }
    }
  }

  async login(): Promise<void> {
    const app = await this.ensureInit();
    await app.loginRedirect({ scopes: SCOPES });
  }

  async logout(): Promise<void> {
    const app = await this.ensureInit();
    await app.logoutRedirect();
  }
}
