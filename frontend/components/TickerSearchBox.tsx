'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Search } from 'lucide-react';

import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { buildStockRoute, normalizeTicker } from '@/lib/stockRoutes';

type TickerSearchBoxProps = {
  defaultValue?: string;
  placeholder?: string;
  destination?: 'summary' | 'dcf';
  className?: string;
};

export default function TickerSearchBox({
  defaultValue = '',
  placeholder = '输入 ticker，例如 COCO / EMPA.TO',
  destination = 'summary',
  className,
}: TickerSearchBoxProps) {
  const router = useRouter();
  const [value, setValue] = useState(defaultValue);

  useEffect(() => {
    setValue(defaultValue);
  }, [defaultValue]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = normalizeTicker(value);
    if (!normalized) {
      return;
    }
    const target = buildStockRoute(normalized, destination);
    if (!target) {
      return;
    }
    router.push(target);
  };

  return (
    <form
      onSubmit={handleSubmit}
      className={cn(
        'flex items-center gap-3 rounded-2xl border border-border/70 bg-background px-4 py-3 shadow-sm',
        className
      )}
    >
      <Search className="h-5 w-5 text-muted-foreground" />
      <Input
        aria-label="Search ticker"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
        className="h-auto flex-1 border-0 bg-transparent px-0 py-0 text-sm font-medium shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
      />
      <span className="hidden rounded-full border border-border/70 px-2 py-1 text-xs text-muted-foreground md:inline">
        Press Enter
      </span>
    </form>
  );
}
