'use client';

import { useState } from 'react';
import { Info } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  formatDynamicFScoreValue,
  normalizeDynamicFScoreCard,
  type DynamicFScoreApiCard,
  type DynamicFScoreFormulaDetails,
  visibleFallbackFormulas,
} from '@/lib/dynamicFScoreCard';

type DynamicFScoreCardProps = {
  ticker: string;
  companyName: string;
  card: DynamicFScoreApiCard;
};

function FormulaInfo({
  formula,
  details,
}: {
  formula: string;
  details: DynamicFScoreFormulaDetails;
}) {
  const [open, setOpen] = useState(false);
  const fallbackFormulas = visibleFallbackFormulas(details);
  const hasFallbacks = fallbackFormulas.length > 0;
  const hasUsedValues = details.usedValues.length > 0;

  return (
    <div
      className="group relative flex min-w-72 items-start gap-2"
      onMouseLeave={() => setOpen(false)}
    >
      <span className="break-words font-mono text-xs text-muted-foreground">{formula || '—'}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0 text-muted-foreground"
        aria-label="F-Score formula details"
        onClick={() => setOpen((current) => !current)}
        onFocus={() => setOpen(true)}
      >
        <Info className="h-4 w-4" aria-hidden="true" />
      </Button>
      <div
        className={[
          'absolute left-0 top-7 z-50 w-[min(30rem,calc(100vw-4rem))] rounded-md border border-border bg-popover p-3 text-xs text-popover-foreground shadow-lg',
          open ? 'block' : 'hidden group-hover:block group-focus-within:block',
        ].join(' ')}
      >
        <div className="space-y-3">
          <div>
            <div className="font-semibold text-foreground">F-Score 标准定义</div>
            <div className="mt-1 text-muted-foreground">{details.standardDefinition || '—'}</div>
          </div>
          <div>
            <div className="font-semibold text-foreground">标准公式</div>
            <div className="mt-1 font-mono text-muted-foreground">{details.standardFormula || '—'}</div>
          </div>
          <div>
            <div className="font-semibold text-foreground">我们的公式 / Fallbacks</div>
            <div className="mt-1 font-mono text-muted-foreground">{details.usedFormula || formula || '—'}</div>
            {hasFallbacks ? (
              <div className="mt-2 space-y-1">
                {fallbackFormulas.map((fallback) => (
                  <div key={fallback} className="font-mono text-muted-foreground">
                    {fallback}
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-1 text-muted-foreground">No fallback formula configured.</div>
            )}
          </div>
          <div>
            <div className="font-semibold text-foreground">实际使用计算的值</div>
            {hasUsedValues ? (
              <div className="mt-1 space-y-1">
                {details.usedValues.map((value) => (
                  <div
                    key={`${value.metricKey}-${value.periodEndDate}-${value.valueNumeric}`}
                    className="font-mono text-muted-foreground"
                  >
                    {value.metricKey || 'unknown'} = {formatDynamicFScoreValue(value.valueNumeric)}
                    {value.periodEndDate ? ` · ${value.periodEndDate}` : ''}
                    {value.factNature ? ` · ${value.factNature}` : ''}
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-1 text-muted-foreground">暂无输入值明细。</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function DynamicFScoreCard({ ticker, companyName, card }: DynamicFScoreCardProps) {
  const model = normalizeDynamicFScoreCard(card);
  const hasRows = model.years.length > 0 && model.rows.length > 0;

  return (
    <Card className="border-border/70 bg-background/80">
      <CardHeader>
        <CardTitle>Dynamic F-Score Card</CardTitle>
        <CardDescription>
          {ticker.toUpperCase()} · {companyName} 过去 5 年的身体素质变化，这是价值投资的“底牌”。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {hasRows ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-20">类别</TableHead>
                <TableHead className="min-w-32">检查项</TableHead>
                <TableHead className="min-w-72">计算公式</TableHead>
                {model.years.map((year) => (
                  <TableHead key={year} className="text-center">
                    {year}
                  </TableHead>
                ))}
                <TableHead className="min-w-20 text-center">状态</TableHead>
                <TableHead className="min-w-56">AI 简评</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {model.rows.map((row) => (
                <TableRow key={row.metricKey || `${row.category}-${row.check}`}>
                  <TableCell className="font-medium text-foreground">{row.category}</TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">{row.check}</TableCell>
                  <TableCell className="min-w-72">
                    <FormulaInfo formula={row.formula} details={row.formulaDetails} />
                  </TableCell>
                  {model.years.map((year, index) => (
                    <TableCell
                      key={`${row.metricKey || row.check}-${year}`}
                      className="text-center font-semibold tabular-nums"
                    >
                      <span className="inline-flex items-center justify-center gap-1">
                        {formatDynamicFScoreValue(row.scores[index])}
                        {row.scoreFactNatures[index] === 'estimate' ? (
                          <Badge
                            variant="warning"
                            className="px-1.5 py-0 text-[10px]"
                            aria-label="estimate"
                          >
                            估
                          </Badge>
                        ) : null}
                      </span>
                    </TableCell>
                  ))}
                  <TableCell className="text-center">
                    <Badge variant={row.statusTone}>{row.status}</Badge>
                  </TableCell>
                  <TableCell className="min-w-56 text-muted-foreground">{row.comment}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <div className="rounded-lg border border-dashed border-border/70 bg-muted/30 p-4 text-sm text-muted-foreground">
            {ticker.toUpperCase()} 暂无可展示的 F-Score 数据。
          </div>
        )}
      </CardContent>
    </Card>
  );
}
