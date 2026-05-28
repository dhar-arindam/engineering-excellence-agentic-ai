import type { NextConfig } from "next";
import { existsSync } from "fs";
import { resolve } from "path";

// Use the real @azure/msal-browser only when it is actually installed.
// This prevents a hard build failure in local / CI environments where Azure
// auth is not needed and the package has not been installed.
const msalInstalled = existsSync(
  resolve(__dirname, "node_modules/@azure/msal-browser")
);
const msalAlias = msalInstalled
  ? undefined
  : resolve(__dirname, "lib/auth/stubs/msal-browser-stub.ts");

const nextConfig: NextConfig = {
  output: "standalone",

  // Turbopack alias (Next.js 16 — top-level turbopack key)
  ...(msalAlias && {
    turbopack: {
      resolveAlias: {
        "@azure/msal-browser": msalAlias,
      },
    },
  }),

  // Webpack alias (fallback for webpack builds)
  ...(msalAlias && {
    webpack(config: { resolve: { alias: Record<string, string> } }) {
      config.resolve.alias = {
        ...config.resolve.alias,
        "@azure/msal-browser": msalAlias,
      };
      return config;
    },
  }),
};

export default nextConfig;
