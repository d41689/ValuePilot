export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center py-12 sm:px-6 lg:px-8 bg-gray-50 dark:bg-zinc-900">
      <div className="w-full max-w-md space-y-8">
        {children}
      </div>
    </div>
  )
}
