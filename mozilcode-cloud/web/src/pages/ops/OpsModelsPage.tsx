import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  api,
  humanProbeMessage,
  type ModelInfo,
  type ProbeResult,
  type ProviderView,
} from '@/lib/api'
import { cn } from '@/lib/utils'

type Props = {
  token: string
  models: ModelInfo[]
  providers: ProviderView[]
  onChanged: () => void
}

export function OpsModelsPage({ token, models, providers, onChanged }: Props) {
  const [form, setForm] = useState({
    name: '',
    display_name: '',
    provider_id: providers[0]?.id ? String(providers[0].id) : '',
    model_id: '',
    sort_order: '0',
    thinking: false,
  })
  const [busy, setBusy] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [probes, setProbes] = useState<Record<number, ProbeResult>>({})

  useEffect(() => {
    if (!form.provider_id && providers[0]?.id) {
      setForm((prev) => ({ ...prev, provider_id: String(providers[0].id) }))
    }
  }, [providers, form.provider_id])

  const create = async () => {
    const payload = {
      name: form.name.trim(),
      display_name: form.display_name.trim(),
      provider_id: Number(form.provider_id),
      model_id: form.model_id.trim(),
      sort_order: Number(form.sort_order || 0),
      is_active: true,
      thinking: form.thinking,
    }
    if (!payload.name || !payload.display_name || !payload.provider_id || !payload.model_id) {
      toast.error('请完整填写模型信息')
      return
    }
    setBusy(true)
    const r = await api('/api/admin/models', { method: 'POST', token, body: payload })
    setBusy(false)
    if (r.error) {
      toast.error(r.error)
      return
    }
    toast.success('模型已保存')
    setForm({
      name: '',
      display_name: '',
      provider_id: providers[0]?.id ? String(providers[0].id) : '',
      model_id: '',
      sort_order: '0',
      thinking: false,
    })
    onChanged()
  }

  const testModel = async (id: number) => {
    setTestingId(id)
    const r = await api<ProbeResult>(`/api/admin/models/${id}/test`, {
      method: 'POST',
      token,
    })
    setTestingId(null)
    if (r.error && r.ok !== true && r.ok !== false) {
      toast.error(r.error)
      return
    }
    setProbes((prev) => ({ ...prev, [id]: r }))
    toast[r.ok ? 'success' : 'error'](
      r.ok ? `${r.display_name || r.model || '模型'} 可用` : humanProbeMessage(r),
    )
  }

  const toggle = async (m: ModelInfo) => {
    const enable = !m.is_active
    const r = await api(`/api/admin/models/${m.id}`, {
      method: 'PUT',
      token,
      body: { is_active: enable },
    })
    if (r.error) {
      toast.error(r.error)
      return
    }
    toast.success(enable ? '已发布到目录' : '已对用户隐藏')
    onChanged()
  }

  const remove = async (m: ModelInfo) => {
    if (!confirm(`确定删除「${m.display_name || m.name}」？`)) return
    const r = await api(`/api/admin/models/${m.id}`, { method: 'DELETE', token })
    if (r.error) {
      toast.error(r.error)
      return
    }
    toast.success('已删除')
    onChanged()
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>添加模型</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <div className="space-y-1.5">
            <Label>显示名</Label>
            <Input
              value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>目录名</Label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>上游模型 ID</Label>
            <Input
              value={form.model_id}
              onChange={(e) => setForm({ ...form, model_id: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>提供商</Label>
            <select
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              value={form.provider_id}
              onChange={(e) => setForm({ ...form, provider_id: e.target.value })}
            >
              {!providers.length ? <option value="">暂无提供商</option> : null}
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label>排序</Label>
            <Input
              value={form.sort_order}
              onChange={(e) => setForm({ ...form, sort_order: e.target.value })}
            />
          </div>
          <label className="flex items-center gap-2 self-end pb-2 text-sm">
            <input
              type="checkbox"
              checked={form.thinking}
              onChange={(e) => setForm({ ...form, thinking: e.target.checked })}
            />
            支持 Thinking
          </label>
          <div className="flex items-end">
            <Button disabled={busy || !providers.length} onClick={() => void create()}>
              保存
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="text-sm text-muted-foreground">{models.length} 个</div>

      {!models.length ? (
        <p className="text-sm text-muted-foreground">还没有模型</p>
      ) : (
        <div className="grid gap-3 xl:grid-cols-2">
          {models.map((m) => {
            const probe = probes[m.id]
            return (
              <Card key={m.id}>
                <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
                  <div>
                    <CardTitle>{m.display_name || m.name}</CardTitle>
                    <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                      <div>
                        目录名 <span className="font-mono text-foreground">{m.name}</span>
                      </div>
                      <div>
                        上游 ID <span className="font-mono text-foreground">{m.model_id}</span>
                      </div>
                      <div>提供商 {m.provider_name || m.provider || '—'}</div>
                    </div>
                  </div>
                  <Badge variant={m.is_active ? 'success' : 'secondary'}>
                    {m.is_active ? '对用户可见' : '已隐藏'}
                  </Badge>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    <Badge variant={m.thinking ? 'default' : 'secondary'}>
                      {m.thinking ? 'Thinking' : '标准'}
                    </Badge>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={testingId === m.id}
                      onClick={() => void testModel(m.id)}
                    >
                      {testingId === m.id ? '测试中…' : '测试'}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => void toggle(m)}>
                      {m.is_active ? '隐藏' : '发布'}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={async () => {
                        const r = await api(`/api/admin/models/${m.id}`, {
                          method: 'PUT', token, body: { thinking: !m.thinking },
                        })
                        if (r.error) toast.error(r.error)
                        else onChanged()
                      }}
                    >
                      {m.thinking ? '关闭 Thinking' : '启用 Thinking'}
                    </Button>
                    <Button variant="destructive" size="sm" onClick={() => void remove(m)}>
                      删除
                    </Button>
                  </div>
                  {probe ? (
                    <div
                      className={cn(
                        'rounded-md border px-3 py-2 text-xs',
                        probe.ok
                          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                          : 'border-red-500/30 bg-red-500/10 text-red-400',
                      )}
                    >
                      <div className="font-semibold">{probe.ok ? '测试通过' : '测试失败'}</div>
                      <div className="mt-0.5">{humanProbeMessage(probe)}</div>
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
