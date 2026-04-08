import Link from 'next/link';

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-6 text-center text-foreground">
      <p className="text-sm font-medium uppercase tracking-[0.3em] text-muted-foreground">
        404
      </p>
      <div className="space-y-2">
        <h1 className="font-display text-4xl font-semibold tracking-tight">
          Page not found
        </h1>
        <p className="text-sm text-muted-foreground">
          The page you requested does not exist in this workspace.
        </p>
      </div>
      <Link
        href="/home"
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
      >
        Go to dashboard
      </Link>
    </main>
  );
}
