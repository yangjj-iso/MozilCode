import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ModelInfo } from '@/lib/api'

export function ModelsPage({ models }: { models: ModelInfo[] }) {
  if (!models.length) {
    return <p className="text-sm text-muted-foreground">暂无可用模型</p>
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {models.map((m) => (
        <Card key={m.id || m.name}>
          <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
            <div>
              <CardTitle className="text-sm">{m.display_name || m.name}</CardTitle>
              <p className="mt-1 font-mono text-xs text-muted-foreground">{m.model_id || m.name}</p>
            </div>
            <Badge variant="secondary">{m.provider_name || m.provider || '—'}</Badge>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            {m.protocol || 'openai-compatible'}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}