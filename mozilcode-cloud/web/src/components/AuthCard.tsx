import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type AuthCardProps = {
  title: string
  subtitle?: string
  mode: 'user' | 'ops'
  loading?: boolean
  error?: string
  onLogin: (email: string, password: string) => Promise<void>
  onRegister?: (email: string, password: string) => Promise<void>
}

export function AuthCard({
  title,
  subtitle,
  mode,
  loading,
  error,
  onLogin,
  onRegister,
}: AuthCardProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  return (
    <div className="grid min-h-screen place-items-center p-6">
      <Card className="w-full max-w-sm shadow-sm">
        <CardHeader>
          <CardTitle className="text-xl tracking-tight">{title}</CardTitle>
          {subtitle ? <p className="text-xs text-muted-foreground">{subtitle}</p> : null}
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="email">邮箱</Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">密码</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void onLogin(email, password)
              }}
            />
          </div>
          {error ? <p className="text-xs text-destructive">{error}</p> : null}
          <div className={mode === 'user' && onRegister ? 'grid grid-cols-2 gap-2 pt-1' : 'pt-1'}>
            <Button
              className="w-full"
              disabled={loading}
              onClick={() => void onLogin(email, password)}
            >
              登录
            </Button>
            {mode === 'user' && onRegister ? (
              <Button
                variant="outline"
                className="w-full"
                disabled={loading}
                onClick={() => void onRegister(email, password)}
              >
                注册
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}