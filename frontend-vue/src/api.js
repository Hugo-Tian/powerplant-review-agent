export async function request(path, options = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), options.timeout ?? 60000)
  try {
    const response = await fetch(`/api${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
      signal: controller.signal,
    })
    const data = await response.json().catch(() => null)
    if (!response.ok) {
      const detail = data?.detail
      throw new Error(Array.isArray(detail)
        ? detail.map(item => `${item.loc.slice(1).join('.')}: ${item.msg}`).join('；')
        : typeof detail === 'string' ? detail : `请求失败（${response.status}），请检查后端是否启动。`)
    }
    return data
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时，请刷新列表确认是否已保存，再决定是否重试。')
    if (error instanceof TypeError) throw new Error('无法连接服务，请检查后端是否启动，然后重试。')
    throw error
  } finally {
    clearTimeout(timeout)
  }
}

const post = (path, body, extra = {}) => request(path, { method: 'POST', body: JSON.stringify(body ?? {}), ...extra })

export async function fetchOrders(userId) {
  const items = []
  let total = 0
  do {
    const page = await request(`/orders?user_id=${encodeURIComponent(userId)}&offset=${items.length}&limit=200`)
    items.push(...page.items)
    total = page.total
    if (!page.items.length) break
  } while (items.length < total)
  return items
}

export const predict = body => post('/predict', body)
export const submitFeedback = (id, body) => post(`/predictions/${encodeURIComponent(id)}/feedback`, body)
export const registerUser = profile => post('/users', {
  user_id: profile.user_id, role: profile.role, responsible_units: profile.responsible_units,
  device_interests: profile.device_interests, mfr_interests: profile.mfr_interests,
  fault_interests: profile.fault_interests, keyword_interests: profile.keyword_interests,
})
export const fetchProfile = userId => request(`/users/${encodeURIComponent(userId)}/profile`)
export const recordBehavior = body => post('/behaviors', body)
export const runPush = userId => post('/push/run', { user_id: userId }, { timeout: 600000 })
export const fetchLlmStatus = () => request('/llm/status')
export const explainPrediction = id => post(`/predictions/${encodeURIComponent(id)}/explain`, {}, { timeout: 120000 })

const roleQuery = role => role ? `role=${encodeURIComponent(role)}` : ''
export const fetchWeights = role => request(`/learning/weights?${roleQuery(role)}`)
export const suggestWeights = role => post(`/learning/weights/suggest?${roleQuery(role)}`)
export const applyWeights = body => request('/learning/weights', { method: 'PUT', body: JSON.stringify(body) })
export const resetWeights = (reviewer, role) => request(`/learning/weights?reviewer=${encodeURIComponent(reviewer)}&${roleQuery(role)}`, { method: 'DELETE' })
export const runPushAll = () => post('/push/run', {}, { timeout: 1200000 })
export const suggestProfiles = () => post('/learning/profile-suggestions', {}, { timeout: 120000 })
export const applyProfiles = body => post('/learning/profile-suggestions/apply', body)
export const fetchMetrics = () => request('/metrics/feedback')
export const fetchTerms = () => request('/terms/candidates')
export const reviewTerm = (term, body) => request(`/terms/candidates/${encodeURIComponent(term)}`, { method: 'PATCH', body: JSON.stringify(body) })
export const fetchVocabulary = () => request('/vocabulary')
export const runAgentReview = id => post(`/predictions/${encodeURIComponent(id)}/agent-review`, {}, { timeout: 300000 })
export const getAgentReview = id => request(`/predictions/${encodeURIComponent(id)}/agent-review`)
export const runDispatch = eventId => post(`/orders/${encodeURIComponent(eventId)}/dispatch-review`, {}, { timeout: 300000 })
export const getDispatch = eventId => request(`/orders/${encodeURIComponent(eventId)}/dispatch-review`)
export const confirmEmergency = (eventId, body) => post(`/orders/${encodeURIComponent(eventId)}/emergency-confirm`, body)
export const runAgentFocus = (userId, limit) => post('/agent/review-focus', { user_id: userId, limit }, { timeout: 1800000 })
