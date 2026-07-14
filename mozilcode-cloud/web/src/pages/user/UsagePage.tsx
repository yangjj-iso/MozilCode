import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { StatCard } from '@/components/StatCard'
import type { UsageData } from '@/lib/api'
import { fmt } from '@/lib/utils'

export function UsagePage({ usage }: { usage: UsageData | null }) {
  const byModel = usage?.by_model || []
  const recent = usage?.recent || []
  const daily = usage?.daily || []

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="请求" value={usage?.total_requests ?? 0} />
        <StatCard label="Tokens" value={usage?.total_tokens ?? 0} />
        <StatCard label="输入" value={usage?.total_input ?? 0} />
        <StatCard label="输出" value={usage?.total_output ?? 0} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>按模型</CardTitle>
          </CardHeader>
          <CardContent>
            {byModel.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>模型</TableHead>
                    <TableHead className="text-right">请求</TableHead>
                    <TableHead className="text-right">Tokens</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {byModel.map((row) => (
                    <TableRow key={row.model}>
                      <TableCell className="font-mono text-xs">{row.model}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(row.total_requests)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmt(row.total_input_tokens + row.total_output_tokens)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-sm text-muted-foreground">暂无数据</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>近 7 日</CardTitle>
          </CardHeader>
          <CardContent>
            {daily.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>日期</TableHead>
                    <TableHead className="text-right">请求</TableHead>
                    <TableHead className="text-right">Tokens</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {daily.map((row) => (
                    <TableRow key={row.date}>
                      <TableCell>{row.date}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmt(row.requests)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {fmt(row.input_tokens + row.output_tokens)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-sm text-muted-foreground">暂无数据</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>最近请求</CardTitle>
        </CardHeader>
        <CardContent>
          {recent.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>模型</TableHead>
                  <TableHead className="text-right">输入</TableHead>
                  <TableHead className="text-right">输出</TableHead>
                  <TableHead className="text-right">延迟</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recent.map((row, i) => (
                  <TableRow key={`${row.created_at}-${i}`}>
                    <TableCell className="text-xs text-muted-foreground">{row.created_at || '—'}</TableCell>
                    <TableCell className="font-mono text-xs">{row.model}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(row.input_tokens)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(row.output_tokens)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmt(row.latency_ms)} ms</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">暂无数据</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}