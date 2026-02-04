'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Activity, FileText, LayoutDashboard, Search, Upload, Star } from 'lucide-react';

import { cn } from '@/lib/utils';

const navigation = [
  { name: 'Dashboard', href: '/home', icon: LayoutDashboard },
  { name: 'Watchlist', href: '/watchlist', icon: Star },
  { name: 'Documents', href: '/documents', icon: FileText },
  { name: 'Upload', href: '/upload', icon: Upload },
  { name: 'Screener', href: '/screener', icon: Search },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="relative min-h-screen bg-background text-foreground">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute -top-24 right-[-6rem] h-64 w-64 rounded-full bg-primary/15 blur-3xl" />
        <div className="absolute bottom-[-8rem] left-[-4rem] h-72 w-72 rounded-full bg-amber-300/30 blur-3xl" />
      </div>
      <div className="mx-auto flex min-h-screen max-w-[1600px] gap-6 p-2">
        <aside className="flex w-56 flex-col gap-6 rounded-2xl border border-border/60 bg-card/90 p-5 shadow-sm backdrop-blur">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <div className="font-display text-lg font-semibold tracking-tight">
                ValuePilot
              </div>
              <div className="text-xs text-muted-foreground">Research Workspace</div>
            </div>
          </div>
          <nav className="flex-1 space-y-1">
            {navigation.map((item) => {
              const Icon = item.icon;
              const isActive = pathname.startsWith(item.href);
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-primary/10 text-primary'
                      : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.name}
                </Link>
              );
            })}
          </nav>
          <div className="rounded-xl border border-dashed border-border/70 bg-background/60 p-3 text-xs text-muted-foreground">
            <div className="font-semibold text-foreground">Tip</div>
            <p className="mt-1">Parsed reports feed the screener instantly. Reparse after fixes.</p>
          </div>
        </aside>

        <main className="flex-1 overflow-auto rounded-2xl border border-border/60 bg-card/85 p-6 shadow-sm backdrop-blur">
          {children}
        </main>
      </div>
    </div>
  );
}
