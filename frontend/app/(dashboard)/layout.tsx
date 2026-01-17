export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b bg-background">
        <div className="container flex h-16 items-center justify-between py-4">
          <div className="font-bold">ValuePilot Dashboard</div>
          <nav className="flex items-center gap-6 text-sm font-medium">
             <a href="/dashboard/home">Home</a>
             <a href="/dashboard/calibration">Calibration</a>
             <a href="/dashboard/screener">Screener</a>
          </nav>
        </div>
      </header>
      <main className="flex-1 space-y-4 p-8 pt-6">
        {children}
      </main>
    </div>
  )
}
