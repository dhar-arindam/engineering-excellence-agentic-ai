/**
 * Stub for @msal/browser — used at build time when the real package is not
 * installed (i.e. when NEXT_PUBLIC_AUTH_MODE !== 'azure').
 *
 * Turbopack / webpack statically resolve all require() paths, so this stub
 * prevents a hard "Module not found" build failure. At runtime in azure mode
 * the real @msal/browser must be installed; AzureAuthStrategy will throw a
 * clear error if the PublicClientApplication stub is ever called.
 */

export class PublicClientApplication {
  constructor(_config: object) {}

  initialize(): Promise<void> {
    return Promise.reject(
      new Error(
        '@msal/browser is not installed. ' +
          'Run `npm install @msal/browser` to enable Azure AD authentication.'
      )
    );
  }

  handleRedirectPromise(): Promise<null> {
    return Promise.resolve(null);
  }

  getAllAccounts(): unknown[] {
    return [];
  }

  acquireTokenSilent(_request: object): Promise<never> {
    return Promise.reject(new Error('@msal/browser stub — not installed.'));
  }

  acquireTokenPopup(_request: object): Promise<never> {
    return Promise.reject(new Error('@msal/browser stub — not installed.'));
  }

  loginRedirect(_request: object): Promise<void> {
    return Promise.reject(new Error('@msal/browser stub — not installed.'));
  }

  logoutRedirect(_request?: object): Promise<void> {
    return Promise.reject(new Error('@msal/browser stub — not installed.'));
  }
}
