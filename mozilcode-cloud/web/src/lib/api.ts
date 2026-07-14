export type ApiResult<T = Record<string, unknown>> = T & {
  error?: string
  _status?: number
}

export type AuthSession = {
  token: string
  email: string
  role: string
}

export type ModelInfo = {
  id: number
  name: string
  display_name: string
  provider?: string
  provider_name?: string
  protocol?: string
  model_id: string
  is_active?: boolean
  provider_id?: number
  thinking?: boolean
}

export type PlanInfo = {
  id?: number
  name: string
  token_quota: number
  duration_days: number
}

export type SubscriptionInfo = {
  plan_name: string
  token_used: number
  token_quota: number
  expires_at: string
}

export type DashboardData = {
  user?: { email?: string; role?: string }
  subscription?: SubscriptionInfo | null
  models?: ModelInfo[]
  plans?: PlanInfo[]
  usage_summary?: {
    total_requests?: number
    total_tokens?: number
    total_input?: number
    total_output?: number
  }
}

export type UsageData = {
  total_input?: number
  total_output?: number
  total_tokens?: number
  total_requests?: number
  by_model?: Array<{
    model: string
    total_input_tokens: number
    total_output_tokens: number
    total_requests: number
  }>
  daily?: Array<{
    date: string
    input_tokens: number
    output_tokens: number
    requests: number
  }>
  recent?: Array<{
    created_at?: string
    model: string
    input_tokens: number
    output_tokens: number
    latency_ms: number
  }>
}

export type ProviderView = {
  id: number
  code: string
  name: string
  protocol?: string
  base_url: string
  api_key_masked?: string
  has_api_key?: boolean
  is_active: boolean
  sort_order?: number
}

export type AdminOverview = {
  users: number
  models: number
  providers: number
  providers_configured: number
  usage_requests?: number
  usage_tokens: number
  plans?: PlanInfo[]
}

export type ProbeResult = {
  ok: boolean
  message?: string
  detail?: string
  latency_ms?: number
  display_name?: string
  model?: string
  name?: string
}

const USER_TOKEN_KEY = 'mozilcode_jwt'
const USER_EMAIL_KEY = 'mozilcode_email'
const OPS_TOKEN_KEY = 'mozilcode_ops_jwt'
const OPS_EMAIL_KEY = 'mozilcode_ops_email'

export function loadUserSession(): AuthSession | null {
  const token = localStorage.getItem(USER_TOKEN_KEY) || ''
  const email = localStorage.getItem(USER_EMAIL_KEY) || ''
  if (!token) return null
  return { token, email, role: 'user' }
}

export function saveUserSession(session: AuthSession | null) {
  if (!session) {
    localStorage.removeItem(USER_TOKEN_KEY)
    localStorage.removeItem(USER_EMAIL_KEY)
    localStorage.removeItem('mozilcode_role')
    return
  }
  localStorage.setItem(USER_TOKEN_KEY, session.token)
  localStorage.setItem(USER_EMAIL_KEY, session.email)
}

export function loadOpsSession(): AuthSession | null {
  const token = localStorage.getItem(OPS_TOKEN_KEY) || ''
  const email = localStorage.getItem(OPS_EMAIL_KEY) || ''
  if (!token) return null
  return { token, email, role: 'admin' }
}

export function saveOpsSession(session: AuthSession | null) {
  if (!session) {
    localStorage.removeItem(OPS_TOKEN_KEY)
    localStorage.removeItem(OPS_EMAIL_KEY)
    return
  }
  localStorage.setItem(OPS_TOKEN_KEY, session.token)
  localStorage.setItem(OPS_EMAIL_KEY, session.email)
}

export async function api<T = Record<string, unknown>>(
  path: string,
  options: {
    method?: string
    body?: unknown
    token?: string | null
  } = {},
): Promise<ApiResult<T>> {
  const { method = 'GET', body, token } = options
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) headers.Authorization = `Bearer ${token}`

  try {
    const res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const contentType = res.headers.get('content-type') || ''
    let data: ApiResult<T> = {} as ApiResult<T>
    if (contentType.includes('application/json')) {
      try {
        data = (await res.json()) as ApiResult<T>
      } catch {
        data = {} as ApiResult<T>
      }
    } else {
      const raw = await res.text()
      data = { raw } as unknown as ApiResult<T>
    }
    if (!res.ok && !data.error) {
      data.error = `请求失败 (${res.status})`
    }
    data._status = res.status
    return data
  } catch (e) {
    return {
      error: e instanceof Error ? e.message : '网络异常',
      _status: 0,
    } as ApiResult<T>
  }
}

export function humanProbeMessage(r?: ProbeResult | null) {
  if (!r) return ''
  if (r.ok) return `可用 · ${Number(r.latency_ms || 0).toLocaleString()} ms`
  const map: Record<string, string> = {
    'api_key empty': '提供商还没有配置密钥',
    'base_url empty': '提供商还没有配置接口地址',
    'provider missing': '模型未绑定有效提供商',
    'auth failed': '密钥无效或无权限',
    'network error': '网络不通或地址不可达',
    'upstream error': '上游返回异常',
    'invalid base_url': '接口地址格式不正确',
    'model not found upstream': '上游找不到该模型 ID',
  }
  const head = (r.message && map[r.message]) || r.message || '测试失败'
  return r.detail ? `${head} · ${r.detail}` : head
}
