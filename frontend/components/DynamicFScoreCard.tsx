import { Badge } from '@/components/ui/badge';
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
} from '@/lib/dynamicFScoreCard';

type DynamicFScoreCardProps = {
  ticker: string;
  companyName: string;
  card: DynamicFScoreApiCard;
};

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
                  {model.years.map((year, index) => (
                    <TableCell
                      key={`${row.metricKey || row.check}-${year}`}
                      className="text-center font-semibold tabular-nums"
                    >
                      {formatDynamicFScoreValue(row.scores[index])}
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
