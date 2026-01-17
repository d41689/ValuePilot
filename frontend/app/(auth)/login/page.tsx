export default function LoginPage() {
  return (
    <div className="rounded-2xl border border-border/60 bg-card/95 p-6 shadow-sm">
      <div className="space-y-2">
        <h1 className="font-display text-2xl font-semibold">Sign in</h1>
        <p className="text-sm text-muted-foreground">
          Authentication wiring is pending for v0.1.
        </p>
      </div>
      <div className="mt-6 rounded-xl border border-dashed border-border/70 bg-muted/30 p-4 text-xs text-muted-foreground">
        Use the dashboard pages directly while auth is finalized.
      </div>
    </div>
  );
}
