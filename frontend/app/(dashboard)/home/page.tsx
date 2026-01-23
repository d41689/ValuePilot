import TickerSearchBox from '@/components/TickerSearchBox';

export default function HomePage() {
  return (
    <div className="flex flex-col gap-6">
      <section className="rounded-2xl border border-border/60 bg-background/70 p-8 shadow-sm">
        <div className="max-w-2xl space-y-3">
          <h1 className="text-2xl font-semibold tracking-tight">快速搜索股票</h1>
          <p className="text-sm text-muted-foreground">
            输入 ticker 并回车，查看公司摘要、估值与关键指标。
          </p>
        </div>
        <div className="mt-6 max-w-xl">
          <TickerSearchBox />
        </div>
      </section>
    </div>
  );
}
