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
import { dynamicFScoreRows, dynamicFScoreYears } from '@/lib/dynamicFScoreCard';

export default function DynamicFScoreCard() {
  return (
    <Card className="border-border/70 bg-background/80">
      <CardHeader>
        <CardTitle>Dynamic F-Score Card</CardTitle>
        <CardDescription>过去 5 年的身体素质变化，这是价值投资的“底牌”。</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-20">类别</TableHead>
              <TableHead className="min-w-32">检查项</TableHead>
              {dynamicFScoreYears.map((year) => (
                <TableHead key={year} className="text-center">
                  {year}
                </TableHead>
              ))}
              <TableHead className="min-w-20 text-center">状态</TableHead>
              <TableHead className="min-w-56">AI 简评</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {dynamicFScoreRows.map((row) => (
              <TableRow key={`${row.category}-${row.check}`}>
                <TableCell className="font-medium text-foreground">{row.category}</TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{row.check}</TableCell>
                {row.scores.map((score, index) => (
                  <TableCell
                    key={`${row.check}-${dynamicFScoreYears[index]}`}
                    className="text-center font-semibold tabular-nums"
                  >
                    {score}
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
      </CardContent>
    </Card>
  );
}
