export default function CalibrationPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-2xl font-semibold">Calibration</h1>
        <p className="text-sm text-muted-foreground">
          Track and review calibration runs for parser accuracy.
        </p>
      </div>
      <div className="rounded-xl border border-dashed border-border/70 bg-muted/30 p-4 text-xs text-muted-foreground">
        No calibration runs are available yet.
      </div>
    </div>
  );
}
