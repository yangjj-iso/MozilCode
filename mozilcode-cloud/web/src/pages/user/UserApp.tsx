import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { AuthCard } from '@/components/AuthCard'
import { Shell, type NavItem } from '@/components/layout/Shell'
import {
  api,
  loadUserSession,
  saveUserSession,
  type AuthSession,
  type DashboardData,
  type UsageData,
} from '@/lib/api'
import { OverviewPage } from './OverviewPage'
import { ModelsPage } from './ModelsPage'
import { PlansPage } from './PlansPage'
import { UsagePage } from './UsagePage'

const NAV: NavItem[] = [
  { to: '/', label: '概览', end: true },
  { to: '/models', label: '模型' },
  { to: '/plans', label: '套餐' },
  { to: '/usage', label: '用量' },
]

function pageTitle(pathname: string) {
  if (pathname === '/') return '概览'
  if (pathname.startsWith('/models')) return '模型'
  if (pathname.startsWith('/plans')) return '套餐'
  if (pathname.startsWith('/usage')) return '用量'
  return 'MozilCode'
}

export function UserApp() {
  const navigate = useNavigate()
  const location = useLocation()
  const [session, setSession] = useState<AuthSession | null>(() => loadUserSession())
  const [authError, setAuthError] = useState('')
  const [authLoading, setAuthLoading] = useState(false)
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [loading, setLoading] = useState(false)

  const title = pageTitle(location.pathname)

  const refresh = useCallback(async (token: string) => {
    setLoading(true)
    const [dash, use] = await Promise.all([
      api<DashboardData>('/api/dashboard', { token }),
      api<UsageData>('/api/usage', { token }),
    ])
    if (dash._status === 401 || use._status === 401) {
      saveUserSession(null)
      setSession(null)
      setDashboard(null)
      setUsage(null)
      setLoading(false)
      return
    }
    if (dash.error) toast.error(dash.error)
    if (use.error) toast.error(use.error)
    setDashboard(dash.error ? null : dash)
    setUsage(use.error ? null : use)
    setLoading(false)
  }, [])

  useEffect(() => {
    if (session?.token) void refresh(session.token)
  }, [session?.token, refresh])

  const handleAuth = async (path: '/api/auth/login' | '/api/auth/register', email: string, password: string) => {
    setAuthLoading(true)
    setAuthError('')
    const r = await api<{ token?: string; email?: string; role?: string }>(path, {
      method: 'POST',
      body: { email, password },
    })
    setAuthLoading(false)
    if (r.error || !r.token) {
      setAuthError(r.error || '登录失败')
      return
    }
    const next: AuthSession = {
      token: r.token,
      email: r.email || email,
      role: r.role || 'user',
    }
    saveUserSession(next)
    setSession(next)
    navigate('/')
  }

  const onLogout = () => {
    saveUserSession(null)
    setSession(null)
    setDashboard(null)
    setUsage(null)
  }

  const email = useMemo(
    () => session?.email || dashboard?.user?.email || '',
    [session?.email, dashboard?.user?.email],
  )

  if (!session) {
    return (
      <AuthCard
        title="MozilCode"
        mode="user"
        loading={authLoading}
        error={authError}
        onLogin={(e, p) => handleAuth('/api/auth/login', e, p)}
        onRegister={(e, p) => handleAuth('/api/auth/register', e, p)}
      />
    )
  }

  return (
    <Shell brand="MozilCode" title={title} email={email} nav={NAV} onLogout={onLogout}>
      <Routes>
        <Route
          index
          element={
            <OverviewPage
              loading={loading}
              dashboard={dashboard}
              usage={usage}
              onRefresh={() => void refresh(session.token)}
            />
          }
        />
        <Route path="models" element={<ModelsPage models={dashboard?.models || []} />} />
        <Route
          path="plans"
          element={
            <PlansPage
              token={session.token}
              plans={dashboard?.plans || []}
              subscription={dashboard?.subscription}
              onRedeemed={() => void refresh(session.token)}
            />
          }
        />
        <Route path="usage" element={<UsagePage usage={usage} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}