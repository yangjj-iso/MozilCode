import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { fmt } from '@/lib/utils'

type StatCardProps = {
  label: string
  value: number | string
  hint?: string
}

export function StatCard({ label, value, hint }: StatCardProps) {
  const display = typeof value === 'number' ? fmt(value) : value
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs font-medium text-muted-foreground">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold tracking-tight tabular-nums">{display}</div>
        {hint ? <div className="mt-1 text-xs text-muted-foreground">{hint}</div> : null}
      </CardContent>
    </Card>
  )
}