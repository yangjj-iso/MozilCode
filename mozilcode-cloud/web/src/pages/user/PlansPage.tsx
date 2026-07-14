import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, type PlanInfo, type SubscriptionInfo } from '@/lib/api'
import { fmt } from '@/lib/utils'

type Props = {
  token: string
  plans: PlanInfo[]
  subscription?: SubscriptionInfo | null
  onRedeemed: () => void
}

export function PlansPage({ token, plans, subscription, onRedeemed }: Props) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)

  const redeem = async () => {
    if (!code.trim()) {
      toast.error('请输入兑换码')
      return
    }
    setBusy(true)
    const r = await api('/api/redeem', {
      method: 'POST',
      token,
      body: { code: code.trim() },
    })
    setBusy(false)
    if (r.error) {
      toast.error(r.error)
      return
    }
    toast.success('兑换成功')
    setCode('')
    onRedeemed()
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>当前订阅</CardTitle>
        </CardHeader>
        <CardContent className="text-sm">
          {subscription ? (
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-muted-foreground">
              <span className="text-foreground">{subscription.plan_name}</span>
              <span className="tabular-nums">
                {fmt(subscription.token_used)} / {fmt(subscription.token_quota)}
              </span>
              <span>到期 {subscription.expires_at || '—'}</span>
            </div>
          ) : (
            <span className="text-muted-foreground">暂无有效订阅</span>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>兑换码</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="redeem-code">兑换码</Label>
            <Input
              id="redeem-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void redeem()
              }}
            />
          </div>
          <Button disabled={busy} onClick={() => void redeem()}>
            兑换
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {plans.map((p) => (
          <Card key={p.id || p.name}>
            <CardHeader>
              <CardTitle>{p.name}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 text-sm text-muted-foreground">
              <div className="tabular-nums text-foreground">{fmt(p.token_quota)} tokens</div>
              <div>{p.duration_days} 天</div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}