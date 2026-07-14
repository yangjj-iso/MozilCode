import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, type ProviderView } from '@/lib/api'

type Props = {
  token: string
  providers: ProviderView[]
  onChanged: () => void
}

export function ProvidersPage({ token, providers, onChanged }: Props) {
  const [form, setForm] = useState({
    code: '',
    name: '',
    base_url: '',
    api_key: '',
    sort_order: '0',
  })
  const [busy, setBusy] = useState(false)
  const [keyTarget, setKeyTarget] = useState<ProviderView | null>(null)
  const [keyValue, setKeyValue] = useState('')

  const create = async () => {
    if (!form.code.trim() || !form.name.trim() || !form.base_url.trim()) {
      toast.error('请填写名称、标识和接口地址')
      return
    }
    setBusy(true)
    const r = await api('/api/admin/providers', {
      method: 'POST',
      token,
      body: {
        code: form.code.trim(),
        name: form.name.trim(),
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim(),
        sort_order: Number(form.sort_order || 0),
        is_active: true,
      },
    })
    setBusy(false)
    if (r.error) {
      toast.error(r.error)
      return
    }
    toast.success('提供商已保存')
    setForm({ code: '', name: '', base_url: '', api_key: '', sort_order: '0' })
    onChanged()
  }

  const toggle = async (p: ProviderView) => {
    const enable = !p.is_active
    const r = await api(`/api/admin/providers/${p.id}`, {
      method: 'PUT',
      token,
      body: { is_active: enable },
    })
    if (r.error) {
      toast.error(r.error)
      return
    }
    toast.success(enable ? '已启用' : '已停用')
    onChanged()
  }

  const remove = async (p: ProviderView) => {
    if (!confirm(`确定删除「${p.name}」？\n删除后不可恢复。`)) return
    const r = await api(`/api/admin/providers/${p.id}`, { method: 'DELETE', token })
    if (r.error) {
      toast.error(r.error)
      return
    }
    toast.success('已删除')
    onChanged()
  }

  const saveKey = async () => {
    if (!keyTarget) return
    if (!keyValue.trim()) {
      toast.error('请输入密钥')
      return
    }
    const r = await api(`/api/admin/providers/${keyTarget.id}`, {
      method: 'PUT',
      token,
      body: { api_key: keyValue.trim() },
    })
    if (r.error) {
      toast.error(r.error)
      return
    }
    toast.success('密钥已更新')
    setKeyTarget(null)
    setKeyValue('')
    onChanged()
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>添加提供商</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <div className="space-y-1.5">
            <Label>名称</Label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>标识</Label>
            <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>接口地址</Label>
            <Input
              value={form.base_url}
              onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>API 密钥</Label>
            <Input
              type="password"
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>排序</Label>
            <Input
              value={form.sort_order}
              onChange={(e) => setForm({ ...form, sort_order: e.target.value })}
            />
          </div>
          <div className="flex items-end">
            <Button disabled={busy} onClick={() => void create()}>
              保存
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <div className="text-sm text-muted-foreground">{providers.length} 个</div>
      </div>

      {!providers.length ? (
        <p className="text-sm text-muted-foreground">还没有提供商</p>
      ) : (
        <div className="grid gap-3 xl:grid-cols-2">
          {providers.map((p) => (
            <Card key={p.id}>
              <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
                <div>
                  <CardTitle>{p.name}</CardTitle>
                  <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                    <div>
                      标识 <span className="font-mono text-foreground">{p.code}</span>
                    </div>
                    <div>
                      地址 <span className="font-mono text-foreground">{p.base_url}</span>
                    </div>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <Badge variant={p.has_api_key ? 'success' : 'warning'}>
                    {p.has_api_key ? '密钥已配置' : '密钥未配置'}
                  </Badge>
                  <Badge variant={p.is_active ? 'success' : 'secondary'}>
                    {p.is_active ? '已启用' : '已停用'}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setKeyTarget(p)
                    setKeyValue('')
                  }}
                >
                  更新密钥
                </Button>
                <Button variant="outline" size="sm" onClick={() => void toggle(p)}>
                  {p.is_active ? '停用' : '启用'}
                </Button>
                <Button variant="destructive" size="sm" onClick={() => void remove(p)}>
                  删除
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={!!keyTarget} onOpenChange={(open) => !open && setKeyTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>更新密钥</DialogTitle>
            <DialogDescription>为「{keyTarget?.name}」设置新的 API 密钥</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              type="password"
              value={keyValue}
              onChange={(e) => setKeyValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void saveKey()
              }}
            />
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setKeyTarget(null)}>
                取消
              </Button>
              <Button onClick={() => void saveKey()}>保存</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}