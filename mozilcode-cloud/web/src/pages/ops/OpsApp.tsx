import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { AuthCard } from '@/components/AuthCard'
import { Shell, type NavItem } from '@/components/layout/Shell'
import {
  api,
  loadOpsSession,
  saveOpsSession,
  type AdminOverview,
  type AuthSession,
  type ModelInfo,
  type PlanInfo,
  type ProviderView,
} from '@/lib/api'
import { OpsOverviewPage } from './OpsOverviewPage'
import { ProvidersPage } from './ProvidersPage'
import { OpsModelsPage } from './OpsModelsPage'
import { UsersPage } from './UsersPage'

export type AdminUser = {
  id: number
  email: string
  role: string
  created_at?: string
}

const NAV: NavItem[] = [
  { to: '/ops', label: '概览', end: true },
  { to: '/ops/providers', label: '提供商' },
  { to: '/ops/models', label: '模型' },
  { to: '/ops/users', label: '用户' },
]

function pageTitle(pathname: string) {
  if (pathname === '/ops' || pathname === '/ops/') return '概览'
  if (pathname.startsWith('/ops/providers')) return '提供商'
  if (pathname.startsWith('/ops/models')) return '模型'
  if (pathname.startsWith('/ops/users')) return '用户'
  return '管理后台'
}

export function OpsApp() {
  const navigate = useNavigate()
  const location = useLocation()
  const [session, setSession] = useState<AuthSession | null>(() => loadOpsSession())
  const [authError, setAuthError] = useState('')
  const [authLoading, setAuthLoading] = useState(false)
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [providers, setProviders] = useState<ProviderView[]>([])
  const [models, setModels] = useState<ModelInfo[]>([])
  const [users, setUsers] = useState<AdminUser[]>([])
  const [plans, setPlans] = useState<PlanInfo[]>([])
  const [loading, setLoading] = useState(false)

  const title = pageTitle(location.pathname)

  const logout = useCallback(() => {
    saveOpsSession(null)
    setSession(null)
    setOverview(null)
    setProviders([])
    setModels([])
    setUsers([])
  }, [])

  const refresh = useCallback(
    async (token: string, notify = false) => {
      setLoading(true)
      const [ov, pv, md, us] = await Promise.all([
        api<AdminOverview & { plans?: PlanInfo[] }>('/api/admin/overview', { token }),
        api<{ providers?: ProviderView[] }>('/api/admin/providers', { token }),
        api<{ models?: ModelInfo[] }>('/api/admin/models', { token }),
        api<{ users?: AdminUser[] }>('/api/admin/users', { token }),
      ])
      setLoading(false)

      if (ov._status === 401 || ov._status === 403) {
        logout()
        toast.error(ov._status === 403 ? '当前账号无管理权限' : '登录已失效')
        return
      }
      if (ov.error) {
        toast.error(ov.error)
        return
      }

      setOverview(ov)
      setPlans(ov.plans || [])
      setProviders(pv.providers || [])
      setModels(md.models || [])
      setUsers(us.users || [])
      if (notify) toast.success('已刷新')
    },
    [logout],
  )

  useEffect(() => {
    if (session?.token) void refresh(session.token)
  }, [session?.token, refresh])

  const login = async (email: string, password: string) => {
    setAuthLoading(true)
    setAuthError('')
    const r = await api<{ token?: string; email?: string; role?: string }>('/api/auth/login', {
      method: 'POST',
      body: { email, password },
    })
    setAuthLoading(false)
    if (r.error || !r.token) {
      setAuthError(r.error || '登录失败')
      return
    }
    if (r.role !== 'admin') {
      setAuthError('当前账号不是管理员')
      return
    }
    const next: AuthSession = {
      token: r.token,
      email: r.email || email,
      role: 'admin',
    }
    saveOpsSession(next)
    setSession(next)
    navigate('/ops')
  }

  if (!session) {
    return (
      <div className="dark min-h-screen bg-background text-foreground">
        <AuthCard
          title="管理后台"
          subtitle="仅管理员账号"
          mode="ops"
          loading={authLoading}
          error={authError}
          onLogin={login}
        />
      </div>
    )
  }

  return (
    <Shell
      brand="MozilCode"
      tag="管理后台"
      title={title}
      email={session.email}
      nav={NAV}
      dark
      onLogout={logout}
    >
      <Routes>
        <Route
          index
          element={
            <OpsOverviewPage
              loading={loading}
              overview={overview}
              plans={plans}
              providers={providers}
              models={models}
              onRefresh={() => void refresh(session.token, true)}
            />
          }
        />
        <Route
          path="providers"
          element={
            <ProvidersPage
              token={session.token}
              providers={providers}
              onChanged={() => void refresh(session.token)}
            />
          }
        />
        <Route
          path="models"
          element={
            <OpsModelsPage
              token={session.token}
              models={models}
              providers={providers}
              onChanged={() => void refresh(session.token)}
            />
          }
        />
        <Route path="users" element={<UsersPage users={users} />} />
        <Route path="*" element={<Navigate to="/ops" replace />} />
      </Routes>
    </Shell>
  )
}