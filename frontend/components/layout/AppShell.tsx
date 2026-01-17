'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { clsx } from 'clsx';
import { LayoutDashboard, FileText, Upload, Search, Activity } from 'lucide-react';

const navigation = [
  { name: 'Dashboard', href: '/home', icon: LayoutDashboard },
  { name: 'Documents', href: '/documents', icon: FileText }, // Placeholder route
  { name: 'Upload', href: '/upload', icon: Upload }, // Placeholder route
  { name: 'Screener', href: '/screener', icon: Search },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex h-screen bg-gray-100">
      {/* Sidebar */}
      <div className="w-64 bg-white shadow-md flex flex-col">
        <div className="p-4 border-b flex items-center gap-2">
          <Activity className="h-6 w-6 text-blue-600" />
          <span className="text-xl font-bold text-gray-800">ValuePilot</span>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          {navigation.map((item) => {
            const Icon = item.icon;
            const isActive = pathname.startsWith(item.href);
            return (
              <Link
                key={item.name}
                href={item.href}
                className={clsx(
                  'flex items-center px-4 py-2 text-sm font-medium rounded-md transition-colors',
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                )}
              >
                <Icon className="mr-3 h-5 w-5" />
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-auto p-8">
        {children}
      </div>
    </div>
  );
}
