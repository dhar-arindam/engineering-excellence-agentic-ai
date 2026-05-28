import type { Metadata } from 'next';
import './globals.css';
import { Sidebar } from '@/components/layout/Sidebar';
import { Providers } from '@/components/providers';

export const metadata: Metadata = {
  title: 'EngineerIQ – Engineering Intelligence Dashboard',
  description: 'Multi-agent code review and engineering quality dashboard',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Injected by the Node.js server on every request so the client bundle can
  // pick up the runtime value of NEXT_PUBLIC_API_URL without needing a rebuild.
  const runtimeEnv = {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000',
  };

  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `window.__ENV=${JSON.stringify(runtimeEnv)}`,
          }}
        />
      </head>
      <body className="bg-[var(--background)] text-[var(--foreground)] antialiased">
        <Providers>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex-1 flex flex-col ml-60">
              {children}
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
