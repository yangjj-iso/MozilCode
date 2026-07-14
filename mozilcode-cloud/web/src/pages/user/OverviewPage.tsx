import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatCard } from '@/components/StatCard'
import type { DashboardData, UsageData } from '@/lib/api'
import { fmt } from '@/lib/utils'

type Props = {
  loading: boolean
  dashboard: DashboardData | null
  usage: UsageData | null
  onRefresh: () => void
}

export function OverviewPage({ loading, dashboard, usage, onRefresh }: Props) {
  const sub = dashboard?.subscription
  const used = sub?.token_used ?? 0
  const quota = sub?.token_quota ?? 0
  const pct = quota > 0 ? Math.min(100, Math.round((used / quota) * 100)) : 0

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground">{loading ? '加载中…' : '账户与用量'}</div>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={loading}>
          刷新
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="请求" value={usage?.total_requests ?? dashboard?.usage_summary?.total_requests ?? 0} />
        <StatCard label="Tokens" value={usage?.total_tokens ?? dashboard?.usage_summary?.total_tokens ?? 0} />
        <StatCard label="可用模型" value={dashboard?.models?.length ?? 0} />
        <StatCard label="套餐" value={sub?.plan_name || '未开通'} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>订阅</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {sub ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>{sub.plan_name}</span>
                <span className="tabular-nums text-muted-foreground">
                  {fmt(used)} / {fmt(quota)} · 到期 {sub.expires_at || '—'}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-secondary">
                <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
              </div>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">暂无有效订阅</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}