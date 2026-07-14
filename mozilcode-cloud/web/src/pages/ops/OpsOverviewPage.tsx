import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { StatCard } from '@/components/StatCard'
import type { AdminOverview, ModelInfo, PlanInfo, ProviderView } from '@/lib/api'
import { fmt } from '@/lib/utils'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type Props = {
  loading: boolean
  overview: AdminOverview | null
  plans: PlanInfo[]
  providers: ProviderView[]
  models: ModelInfo[]
  onRefresh: () => void
}

const COLORS = ['#7aa2ff', '#3ecf8e', '#f0b429', '#c4b5fd', '#fb7185', '#67e8f9']

export function OpsOverviewPage({ loading, overview, plans, providers, models, onRefresh }: Props) {
  const providerChart = [
    { name: '已配置密钥', value: overview?.providers_configured ?? 0 },
    {
      name: '未配置',
      value: Math.max(0, (overview?.providers ?? 0) - (overview?.providers_configured ?? 0)),
    },
  ]

  const modelByProvider = Object.entries(
    models.reduce<Record<string, number>>((acc, m) => {
      const key = m.provider_name || m.provider || '未绑定'
      acc[key] = (acc[key] || 0) + 1
      return acc
    }, {}),
  ).map(([name, value]) => ({ name, value }))

  const planChart = plans.map((p) => ({
    name: p.name,
    tokens: p.token_quota,
  }))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground">{loading ? '加载中…' : '系统概览'}</div>
        <Button variant="outline" size="sm" onClick={onRefresh} disabled={loading}>
          刷新
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="用户" value={overview?.users ?? 0} />
        <StatCard
          label="提供商"
          value={overview?.providers ?? 0}
          hint={`已配置密钥 ${fmt(overview?.providers_configured ?? 0)}`}
        />
        <StatCard label="模型" value={overview?.models ?? 0} />
        <StatCard
          label="用量 Tokens"
          value={overview?.usage_tokens ?? 0}
          hint={`请求 ${fmt(overview?.usage_requests ?? 0)}`}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>提供商密钥</CardTitle>
          </CardHeader>
          <CardContent className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={providerChart} dataKey="value" nameKey="name" innerRadius={48} outerRadius={72}>
                  {providerChart.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>模型分布</CardTitle>
          </CardHeader>
          <CardContent className="h-56">
            {modelByProvider.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={modelByProvider}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(0 0% 100% / 0.08)" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#7aa2ff" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground">暂无模型</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>套餐配额</CardTitle>
          </CardHeader>
          <CardContent className="h-56">
            {planChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={planChart}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(0 0% 100% / 0.08)" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="tokens" fill="#3ecf8e" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-muted-foreground">暂无套餐</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>提供商状态</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {providers.slice(0, 6).map((p) => (
              <div key={p.id} className="flex items-center justify-between gap-2">
                <span>{p.name}</span>
                <span className="text-xs text-muted-foreground">
                  {p.has_api_key ? '密钥已配置' : '密钥未配置'} · {p.is_active ? '启用' : '停用'}
                </span>
              </div>
            ))}
            {!providers.length ? <p className="text-muted-foreground">暂无提供商</p> : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>模型状态</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {models.slice(0, 6).map((m) => (
              <div key={m.id} className="flex items-center justify-between gap-2">
                <span>{m.display_name || m.name}</span>
                <span className="text-xs text-muted-foreground">
                  {m.is_active ? '对用户可见' : '已隐藏'}
                </span>
              </div>
            ))}
            {!models.length ? <p className="text-muted-foreground">暂无模型</p> : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}