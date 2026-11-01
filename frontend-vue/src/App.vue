<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import {
  explainPrediction, fetchLlmStatus, fetchOrders, fetchProfile, getAgentReview, predict, recordBehavior,
  runAgentFocus, runAgentReview,
  registerUser, runPush, submitFeedback,
} from './api.js'
import ScoreGauge from './components/ScoreGauge.vue'
import LearningView from './components/LearningView.vue'
import dataset from '../../data/synthetic/dataset.json'
import sampleRequests from '../../data/synthetic/predict_requests.json'

const profiles = dataset.profiles
const view = ref('bench')
const userId = ref(profiles[0].user_id)
const profile = computed(() => profiles.find(p => p.user_id === userId.value))
const rows = ref([])
const learned = ref(null)
const llm = ref(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const search = ref('')
const status = ref('all')
const sorting = ref('score')
const page = ref(1)
const PAGE = 10
const selectedId = ref(null)
const selected = computed(() => rows.value.find(r => r.order.event_id === selectedId.value))
const types = { emergency: '紧急推送', personal: '个性化推送', device_group: '同类设备推送' }
const statuses = { pending: '待确认', confirm: '已确认', correct: '已修改' }
const dimensions = { device_type: '设备类型', behavior: '行为兴趣', role: '岗位职责', manufacturer: '厂家匹配' }
const tagSources = { llm: '大模型', merged: '规则与 TF-IDF', rule: '规则', tfidf: 'TF-IDF' }
const progress = ref(null)
const reviewer = ref('演示审核人')
const modal = ref(null)
const modalKind = ref('confirm')
const modalError = ref('')
const target = ref(null)
const form = reactive({ comment: '', score: 0, type: 'personal', title: '', content: '', level: '一般', unit: '#1' })
const explanations = reactive({})
const agentRuns = reactive({})
const agentBatch = ref(null)
const agentLimit = ref(10)
const recClass = { push: 'go', no_push: 'stop', needs_human: 'ask' }
const confLabel = { low: '把握低', medium: '把握中等', high: '把握高' }
const reviewLabel = { agreed: '复核智能体同意调查结论', agreed_after_revision: '退回修改一次后，复核智能体同意',
  challenged: '复核智能体仍有异议，结论已降级为需人工判断', skipped: '未经复核' }
const engineLabel = { openjiuwen: '（openJiuwen ReActAgent 驱动）',
  openjiuwen_team: '（openJiuwen 多智能体：理解 → 调查 → 复核）' }
const agentPending = computed(() => rows.value.filter(r => needsReview(r) && !r.agent_review).length)

const needsReview = r => r.effective_result.review_status === 'pending' && !!r.latest_prediction.triage?.needs_review
const level = r => r.latest_prediction.effective_level || r.order.level
const filtered = computed(() => {
  const term = search.value.trim().toLowerCase()
  const result = rows.value.filter(r =>
    (status.value === 'all' || (status.value === 'focus' ? needsReview(r) : r.effective_result.review_status === status.value)) &&
    (!term || `${r.order.title} ${r.order.event_id} ${r.order.content}`.toLowerCase().includes(term)))
  if (sorting.value === 'score') result.sort((a, b) => b.effective_result.score - a.effective_result.score)
  return result
})
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE)))
const pageRows = computed(() => filtered.value.slice((page.value - 1) * PAGE, page.value * PAGE))
const pending = computed(() => rows.value.filter(r => r.effective_result.review_status === 'pending').length)
const focusCount = computed(() => rows.value.filter(needsReview).length)
const urgentPending = computed(() => rows.value.filter(r => r.effective_result.review_status === 'pending' && r.effective_result.push_type === 'emergency').length)
const reviewed = computed(() => rows.value.length - pending.value)
const topInterests = computed(() => {
  const p = learned.value?.profile
  if (!p) return []
  return [...Object.entries(p.device_interests), ...Object.entries(p.fault_interests),
    ...Object.entries(p.keyword_interests), ...Object.entries(p.mfr_interests)]
    .sort((a, b) => b[1] - a[1]).slice(0, 6)
})
watch([search, status, sorting], () => { page.value = 1 })
const formatScore = value => Number(value).toFixed(4)
const formatTime = value => new Date(value).toLocaleString('zh-CN', { hour12: false })
const percent = value => `${Math.round(value * 100)}%`

async function refreshProfile() {
  try { learned.value = await fetchProfile(userId.value) } catch { learned.value = null }
}
async function load({ clearNotice = false } = {}) {
  loading.value = true
  error.value = ''
  if (clearNotice) notice.value = ''
  try {
    await registerUser(profile.value)
    rows.value = await fetchOrders(userId.value)
    await refreshProfile()
    if (!selected.value) selectedId.value = rows.value[0]?.order.event_id ?? null
    page.value = Math.min(page.value, pageCount.value)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
async function changeProfile() {
  rows.value = []
  selectedId.value = null
  page.value = 1
  await load({ clearNotice: true })
}
function selectOrder(row) {
  selectedId.value = row.order.event_id
  // 埋点：查看详情行为用于画像建模；失败不影响页面操作
  recordBehavior({ user_id: userId.value, action_type: 'detail', event_id: row.order.event_id })
    .then(refreshProfile).catch(() => {})
}
function openSimilar(eventId) {
  const row = rows.value.find(r => r.order.event_id === eventId)
  if (row) selectOrder(row)
}
async function importSamples() {
  busy.value = true
  error.value = ''
  notice.value = ''
  const existing = new Set(rows.value.map(r => r.order.event_id))
  const missing = sampleRequests.filter(r => !existing.has(r.order.event_id))
  progress.value = { done: 0, total: missing.length }
  let failure = ''
  try {
    // 4 条并发：启用大模型后单条预测需要数秒
    const queue = [...missing]
    let stop = null
    const worker = async () => {
      while (queue.length && !stop) {
        const item = queue.shift()
        try {
          await predict({ order: item.order, user_id: userId.value })
          progress.value.done++
        } catch (e) {
          stop = stop || e
        }
      }
    }
    await Promise.all(Array.from({ length: 4 }, worker))
    if (stop) throw stop
    notice.value = missing.length ? `已为${profile.value.role}导入并预测 ${missing.length} 条模拟工单。` : '当前岗位的模拟工单已全部导入，无需重复导入。'
  } catch (e) {
    failure = `已完成 ${progress.value.done} 条，其余尚未导入。${e.message} 再次导入会跳过已有工单。`
  } finally {
    progress.value = null
    await load()
    if (failure) error.value = failure
    busy.value = false
  }
}
async function repush() {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const summary = (await runPush(userId.value)).users[0]
    notice.value = `已按最新画像重新评分 ${summary.scored} 条工单，其中 ${summary.saved} 条结果有变化（重新进入待确认）。`
  } catch (e) {
    error.value = e.message
  } finally {
    await load()
    busy.value = false
  }
}
async function explain(row) {
  const id = row.latest_prediction.prediction_id
  explanations[id] = { status: 'loading' }
  try {
    explanations[id] = await explainPrediction(id)
  } catch (e) {
    explanations[id] = { status: 'error', error: e.message }
  }
}
async function investigate(row) {
  const id = row.latest_prediction.prediction_id
  agentRuns[id] = { status: 'loading' }
  try {
    agentRuns[id] = await runAgentReview(id)
    row.agent_review = { ...agentRuns[id] }
  } catch (e) {
    agentRuns[id] = { status: 'error', error: e.message }
  }
}
async function preReviewFocus() {
  busy.value = true
  error.value = ''
  notice.value = ''
  const total = Math.max(1, Math.min(Math.round(Number(agentLimit.value) || 1), agentPending.value))
  agentLimit.value = total
  agentBatch.value = { done: 0, total, stop: false }
  const all = []
  try {
    // 每批最多 2 条，逐批请求，便于显示进度和随时停止
    while (!agentBatch.value.stop && all.length < total) {
      const out = await runAgentFocus(userId.value, Math.min(2, total - all.length))
      all.push(...out.reviewed)
      agentBatch.value.done = all.length
      if (!out.reviewed.length || !out.remaining) break
    }
    const count = rec => all.filter(r => r.recommendation === rec).length
    notice.value = `审核助手预审了 ${all.length} 条重点审核工单：建议推送 ${count('push')} 条，建议不推送 ${count('no_push')} 条，需人工判断 ${count('needs_human')} 条。` +
      (agentPending.value - all.length > 0 ? `还有 ${agentPending.value - all.length} 条重点工单未预审。` : '')
  } catch (e) {
    error.value = `已预审 ${all.length} 条后出错：${e.message}`
  } finally {
    agentBatch.value = null
    await load()
    busy.value = false
  }
}
watch(agentPending, n => {
  // 默认 10 条，且不超过当前待预审数量
  if (!agentBatch.value) agentLimit.value = Math.max(1, Math.min(agentLimit.value || 10, n || 1))
})
watch(selected, row => {
  const id = row?.latest_prediction.prediction_id
  if (row?.agent_review && id && !agentRuns[id]) {
    agentRuns[id] = { status: 'loading' }
    getAgentReview(id).then(r => { agentRuns[id] = r }).catch(() => { delete agentRuns[id] })
  }
})
async function adoptAgent(row) {
  const run = agentRuns[row.latest_prediction.prediction_id]
  const agrees = Math.abs(run.suggested_score - row.latest_prediction.score) <= 0.05
  await openModal(agrees ? 'confirm' : 'correct', row)
  if (!agrees) form.score = run.suggested_score
  form.comment = `审核助手建议：${run.summary}`
}
async function openModal(kind, row = selected.value) {
  target.value = row ? { predictionId: row.latest_prediction.prediction_id, title: row.order.title } : null
  modalKind.value = kind
  modalError.value = ''
  form.comment = ''
  form.score = row?.effective_result.score ?? 0
  form.type = row?.effective_result.push_type ?? 'personal'
  form.title = ''
  form.content = ''
  form.level = '一般'
  form.unit = '#1'
  await nextTick()
  modal.value.showModal()
}
async function save() {
  modalError.value = ''
  busy.value = true
  let saved = false
  try {
    if (modalKind.value === 'create') {
      const result = await predict({
        order: { event_id: `MANUAL-${crypto.randomUUID()}`, title: form.title.trim(), content: form.content.trim(),
          level: form.level, unit_no: form.unit || null },
        user_id: userId.value,
      })
      selectedId.value = result.event_id
      notice.value = '工单已保存并完成预测。'
    } else {
      const body = { action: modalKind.value, reviewer: reviewer.value.trim(), comment: form.comment.trim() }
      if (modalKind.value === 'correct') {
        body.corrected_score = Number(form.score)
        body.corrected_push_type = form.type
      }
      await submitFeedback(target.value.predictionId, body)
      notice.value = modalKind.value === 'confirm' ? '已确认原模型结果，反馈已保存。' : '人工修改已保存，原模型结果保留在历史中。'
    }
    saved = true
  } catch (e) {
    modalError.value = e.message
  } finally {
    busy.value = false
  }
  if (saved) {
    modal.value.close()
    await load()
  }
}
onMounted(() => {
  load()
  fetchLlmStatus().then(v => { llm.value = v }).catch(() => {})
})
</script>

<template>
  <div class="shell">
    <nav class="rail" aria-label="主导航">
      <a class="brand" href="/" aria-label="工单推送首页">
        <svg viewBox="0 0 40 40" aria-hidden="true"><rect x="3" y="3" width="34" height="34" rx="3" /><path d="M22 7 12 22h8l-2 11 10-15h-8z" /></svg>
        <span>工单推送<small>电厂运维</small></span>
      </a>
      <div class="nav-items">
        <button :aria-current="view === 'bench' ? 'page' : null" @click="view = 'bench'">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 4h14M3 10h14M3 16h9" /></svg>推送工作台
        </button>
        <button :aria-current="view === 'learn' ? 'page' : null" @click="view = 'learn'">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 16 8 10l3 3 6-8" /></svg>学习与评估
        </button>
      </div>
      <div class="lamp-box" :class="{ on: llm?.enabled }">
        <span class="lamp" aria-hidden="true"></span>
        <p>{{ llm?.enabled ? '大模型在线' : '大模型未启用' }}<small>{{ llm?.enabled ? llm.model : '仅规则 + TF-IDF' }}</small></p>
      </div>
      <a class="docs-link" href="/docs" target="_blank" rel="noreferrer">接口文档</a>
    </nav>

    <main>
      <header class="topbar">
        <div>
          <h1>{{ view === 'bench' ? '推送工作台' : '学习与评估' }}</h1>
          <p>{{ view === 'bench' ? '看清每条推送的依据，再决定是否认可。' : '用人工审核结果检验模型，并决定要不要调整它。' }}</p>
        </div>
        <label class="role-picker">当前岗位
          <select v-model="userId" @change="changeProfile" :disabled="busy || loading" aria-label="当前岗位">
            <option v-for="p in profiles" :key="p.user_id" :value="p.user_id">{{ p.role }}（模拟）</option>
          </select>
        </label>
      </header>

      <template v-if="view === 'bench'">
        <section class="annunciator" aria-label="当前岗位工单概况">
          <div class="cell"><span>工单</span><strong>{{ rows.length }}</strong></div>
          <div class="cell"><span>待人工确认</span><strong>{{ pending }}</strong></div>
          <button class="cell amber" :class="{ lit: focusCount }" @click="status = 'focus'" :disabled="!focusCount">
            <span>需重点审核</span><strong>{{ focusCount }}</strong>
          </button>
          <div class="cell red" :class="{ lit: urgentPending }"><span>紧急待确认</span><strong>{{ urgentPending }}</strong></div>
          <div class="cell green"><span>已确认或修改</span><strong>{{ reviewed }}</strong></div>
        </section>

        <section class="profile-strip" aria-label="当前用户画像">
          <div class="profile-meta">
            <strong>{{ profile.role }}的画像</strong>
            <span v-if="learned">近 30 天 {{ learned.behavior_count }} 条行为，{{ formatTime(learned.computed_at) }} 更新</span>
            <span v-else>画像暂不可用</span>
          </div>
          <ul class="interest-bars">
            <li v-for="[code, value] in topInterests" :key="code"><span>{{ code }}</span><i :style="{ '--v': value }"></i><b>{{ value.toFixed(2) }}</b></li>
          </ul>
          <div class="strip-actions">
            <button @click="repush" :disabled="busy || loading || !rows.length">按最新画像重新推送</button>
          </div>
        </section>

        <div class="actions">
          <button @click="importSamples" :disabled="busy || loading">{{ progress ? `正在导入 ${progress.done}/${progress.total}` : '导入模拟工单（320 条）' }}</button>
          <button v-if="agentBatch" @click="agentBatch.stop = true" :disabled="agentBatch.stop">{{ agentBatch.stop ? '正在停止…' : `停止预审（${agentBatch.done}/${agentBatch.total}）` }}</button>
          <div v-else class="agent-batch" :title="llm?.enabled ? '' : '配置大模型后可用'">
            <label>预审<input v-model.number="agentLimit" type="number" min="1" :max="Math.max(1, agentPending)" step="1" aria-label="预审条数" :disabled="busy || loading || !llm?.enabled || !agentPending" />条</label>
            <button @click="preReviewFocus" :disabled="busy || loading || !llm?.enabled || !agentPending">助手预审重点工单（待预审 {{ agentPending }}）</button>
          </div>
          <button class="primary" @click="openModal('create', null)" :disabled="busy || loading">新建工单并预测</button>
        </div>
        <div v-if="agentBatch" class="import-progress"><progress :value="agentBatch.done" :max="agentBatch.total || 1"></progress><span>审核助手正在逐条调查，已完成 {{ agentBatch.done }} / {{ agentBatch.total }} 条，每条约 10 秒。可以随时停止，已完成的结果会保留。</span></div>
        <div v-if="progress" class="import-progress" role="status"><progress :value="progress.done" :max="progress.total || 1"></progress><span>正在计算并保存推送结果，请保持页面打开。</span></div>
        <div v-if="error" class="message error" role="alert">{{ error }} <button @click="load()" :disabled="busy || loading">重新加载</button></div>
        <div v-if="notice" class="message success" role="status">{{ notice }}</div>

        <div class="workbench">
          <section class="queue" aria-label="工单列表">
            <div class="queue-head">
              <h2>工单队列 <span>{{ filtered.length }}</span></h2>
              <button class="text-button" @click="load({ clearNotice: true })" :disabled="busy || loading">{{ loading ? '加载中…' : '刷新列表' }}</button>
            </div>
            <div class="filters">
              <input v-model="search" type="search" placeholder="搜索工单标题、编号或内容" aria-label="搜索工单" />
              <select v-model="status" aria-label="审核状态"><option value="all">全部状态</option><option value="focus">需重点审核</option><option value="pending">待确认</option><option value="confirm">已确认</option><option value="correct">已修改</option></select>
              <select v-model="sorting" aria-label="排序方式"><option value="score">按当前匹配分</option><option value="time">按最近预测</option></select>
            </div>
            <div v-if="loading && !rows.length" class="empty">正在读取工单…</div>
            <div v-else-if="!rows.length" class="empty"><h3>{{ error ? '工单暂时无法读取' : '这个岗位还没有推送工单' }}</h3><p>{{ error ? '检查服务连接后，点击重新加载。' : '导入模拟工单查看排序，或新建一条工单开始预测。' }}</p></div>
            <div v-else-if="!filtered.length" class="empty"><h3>没有符合条件的工单</h3><button @click="search = ''; status = 'all'">清除筛选</button></div>
            <div v-else class="table-scroll"><table>
              <thead><tr><th>工单</th><th class="score-col">匹配分</th><th>审核</th><th><span class="sr-only">操作</span></th></tr></thead>
              <tbody>
                <tr v-for="row in pageRows" :key="row.order.event_id" :class="[row.effective_result.push_type, { selected: selectedId === row.order.event_id }]">
                  <td class="order-cell">
                    <div class="order-meta">
                      <span class="level" :class="{ urgent: level(row) === '紧急', raised: level(row) !== row.order.level }">{{ level(row) !== row.order.level ? `${row.order.level}→${level(row)}` : row.order.level }}</span>
                      <span class="eid">{{ row.order.event_id }}</span>
                      <span v-if="needsReview(row)" class="focus-dot" title="需重点审核">需重点审核</span>
                    </div>
                    <button class="order-title" @click="selectOrder(row)">{{ row.order.title }}</button>
                    <small>{{ row.order.unit_no || '机组未填写' }}，{{ row.order.device_type_name || '设备见正文' }}</small>
                  </td>
                  <td class="score-col">
                    <strong class="score">{{ formatScore(row.effective_result.score) }}</strong>
                    <ScoreGauge :score="row.effective_result.score" :type="row.effective_result.push_type" />
                    <small>{{ types[row.effective_result.push_type] }}</small>
                  </td>
                  <td><span class="status" :class="row.effective_result.review_status">{{ statuses[row.effective_result.review_status] }}</span><small class="cell-line">{{ row.effective_result.source === 'human' ? '人工结果' : '模型建议' }}</small><span v-if="row.agent_review && row.effective_result.review_status === 'pending'" class="agent-chip" :class="recClass[row.agent_review.recommendation]">助手：{{ row.agent_review.recommendation_label }}<template v-if="row.agent_review.suggested_score != null"> {{ row.agent_review.suggested_score.toFixed(2) }}</template></span></td>
                  <td><div class="row-actions"><button @click="openModal('confirm', row)" :disabled="busy || loading">确认</button><button @click="openModal('correct', row)" :disabled="busy || loading">修改</button></div></td>
                </tr>
              </tbody>
            </table></div>
            <footer class="pagination"><span>第 {{ page }} / {{ pageCount }} 页，共 {{ filtered.length }} 条</span><div><button @click="page--" :disabled="page <= 1">上一页</button><button @click="page++" :disabled="page >= pageCount">下一页</button></div></footer>
          </section>

          <aside class="faceplate" aria-label="工单详情">
            <template v-if="selected">
              <header class="fp-head">
                <span class="eid">{{ selected.order.event_id }}</span>
                <h2>{{ selected.order.title }}</h2>
                <p class="order-content">{{ selected.order.content || '未填写正文' }}</p>
              </header>

              <section class="fp-score" :class="selected.effective_result.push_type">
                <div class="fp-score-row">
                  <strong>{{ formatScore(selected.effective_result.score) }}</strong>
                  <span>{{ types[selected.effective_result.push_type] }}<small>{{ selected.effective_result.source === 'human' ? `人工修正，模型原始分 ${formatScore(selected.latest_prediction.score)}` : '模型建议，置信度未校准' }}</small></span>
                </div>
                <ScoreGauge size="panel" :score="selected.effective_result.score" :type="selected.effective_result.push_type" :original="selected.latest_prediction.score" />
              </section>

              <section v-if="selected.latest_prediction.triage?.needs_review" class="fp-block amber">
                <h3>为什么需要重点审核</h3>
                <ul><li v-for="reason in selected.latest_prediction.triage.reasons" :key="reason">{{ reason }}</li></ul>
              </section>
              <section v-if="selected.latest_prediction.triage?.needs_review || agentRuns[selected.latest_prediction.prediction_id]" class="fp-section agent" aria-label="审核助手">
                <h3>审核助手</h3>
                <template v-if="agentRuns[selected.latest_prediction.prediction_id]?.status === 'ok' || agentRuns[selected.latest_prediction.prediction_id]?.status === 'incomplete'">
                  <div class="verdict-row" :class="recClass[agentRuns[selected.latest_prediction.prediction_id].recommendation]">
                    <strong>{{ agentRuns[selected.latest_prediction.prediction_id].recommendation_label }}</strong>
                    <span v-if="agentRuns[selected.latest_prediction.prediction_id].suggested_score != null">建议分 {{ agentRuns[selected.latest_prediction.prediction_id].suggested_score.toFixed(2) }}</span>
                    <span>{{ confLabel[agentRuns[selected.latest_prediction.prediction_id].confidence] }}</span>
                  </div>
                  <p class="agent-summary">{{ agentRuns[selected.latest_prediction.prediction_id].summary }}</p>
                  <ul v-if="agentRuns[selected.latest_prediction.prediction_id].evidence?.length" class="evidence">
                    <li v-for="e in agentRuns[selected.latest_prediction.prediction_id].evidence" :key="e.fact"><b>{{ ({ get_order: '工单', get_prediction: '本条评分', get_user_profile: '用户画像', search_similar: '相似工单', recent_unit_orders: '同机组工单', user_review_history: '本人审核历史', what_if: '试算', get_understanding: '工单理解', list_recipients: '各专工推送' })[e.tool] || e.tool }}</b>{{ e.fact }}<em v-if="e.unverified" class="unverified" :title="`数字 ${e.unverified.join('、')} 在该工具的返回结果中找不到`">未核实</em></li>
                  </ul>
                  <div v-if="agentRuns[selected.latest_prediction.prediction_id].review" class="team-block" :class="agentRuns[selected.latest_prediction.prediction_id].review.status">
                    <b>复核</b>
                    <span>{{ reviewLabel[agentRuns[selected.latest_prediction.prediction_id].review.status] }}</span>
                    <ul v-for="(v, i) in agentRuns[selected.latest_prediction.prediction_id].review.verdicts" :key="i">
                      <li v-for="issue in v.issues" :key="issue">第 {{ i + 1 }} 轮异议：{{ issue }}</li>
                    </ul>
                  </div>
                  <div v-if="agentRuns[selected.latest_prediction.prediction_id].understanding" class="team-block">
                    <b>工单理解</b>
                    <span v-if="agentRuns[selected.latest_prediction.prediction_id].understanding.devices.length">
                      设备：<template v-for="(d, i) in agentRuns[selected.latest_prediction.prediction_id].understanding.devices" :key="d.code">{{ i ? '、' : '' }}{{ d.name }}（原文“{{ d.span }}”）</template>
                    </span>
                    <span v-else>原文没有能明确对应的设备</span>
                    <span v-if="agentRuns[selected.latest_prediction.prediction_id].understanding.level">；实际等级：{{ agentRuns[selected.latest_prediction.prediction_id].understanding.level }}</span>
                    <ul class="dispatch">
                      <li v-for="m in agentRuns[selected.latest_prediction.prediction_id].dispatch?.missed || []" :key="'m' + m.user_id" class="missed">可能漏推：{{ m.role }}（当前分 {{ m.current_score == null ? '未计算' : m.current_score.toFixed(2) }}）— {{ m.reason }}</li>
                      <li v-for="m in agentRuns[selected.latest_prediction.prediction_id].dispatch?.extra || []" :key="'e' + m.user_id" class="extra">可能误推：{{ m.role }}（当前分 {{ m.current_score.toFixed(2) }}）</li>
                    </ul>
                  </div>
                  <details class="trace">
                    <summary>调查过程：{{ agentRuns[selected.latest_prediction.prediction_id].tool_calls }} 步，{{ (agentRuns[selected.latest_prediction.prediction_id].duration_ms / 1000).toFixed(1) }} 秒</summary>
                    <ol>
                      <li v-for="(st, i) in agentRuns[selected.latest_prediction.prediction_id].steps" :key="i" :class="{ failed: !st.ok }">
                        <span v-if="st.agent_label" class="step-agent">{{ st.agent_label }}</span>
                        <span class="step-tool">{{ st.label }}</span>
                        <span>{{ st.summary }}</span>
                        <small v-if="Object.keys(st.args || {}).length">参数 {{ JSON.stringify(st.args) }}</small>
                        <small v-if="st.thought" class="thought">“{{ st.thought }}”</small>
                      </li>
                    </ol>
                    <p v-for="n in agentRuns[selected.latest_prediction.prediction_id].notes || []" :key="n" class="fine">{{ n }}</p>
                    <p v-if="agentRuns[selected.latest_prediction.prediction_id].dropped_evidence?.length" class="fine">有 {{ agentRuns[selected.latest_prediction.prediction_id].dropped_evidence.length }} 条证据因无法追溯到实际调用的工具而作废。</p>
                  </details>
                  <div class="row-actions agent-actions">
                    <button v-if="selected.effective_result.review_status === 'pending' && agentRuns[selected.latest_prediction.prediction_id].recommendation !== 'needs_human'" class="primary" @click="adoptAgent(selected)" :disabled="busy">按建议审核</button>
                    <button class="text-button" @click="investigate(selected)" :disabled="busy">重新调查</button>
                  </div>
                  <p class="fine">由 {{ agentRuns[selected.latest_prediction.prediction_id].model }}{{ engineLabel[agentRuns[selected.latest_prediction.prediction_id].engine] || '' }} 自主调查得出，只是建议，不会修改任何分数。</p>
                </template>
                <p v-else-if="agentRuns[selected.latest_prediction.prediction_id]?.status === 'loading'" class="agent-loading">审核助手正在调查：查评分、看画像、翻相似工单…</p>
                <p v-else-if="agentRuns[selected.latest_prediction.prediction_id]?.status === 'error'" class="message error">调查失败：{{ agentRuns[selected.latest_prediction.prediction_id].error }}</p>
                <template v-else>
                  <p class="fine">让审核助手像值班工程师一样自主调查这条推送：查评分构成、用户画像、相似工单的人工结论、你过去的审核习惯，再给出建议和证据。</p>
                  <button @click="investigate(selected)" :disabled="!llm?.enabled || busy">让审核助手调查</button>
                  <p v-if="!llm?.enabled" class="fine">配置大模型后可用。</p>
                </template>
              </section>
              <section v-if="selected.latest_prediction.analysis?.level_review" class="fp-block ai-review">
                <h3>AI 等级复核：{{ selected.latest_prediction.analysis.level_review.from_level }} 上调为 {{ selected.latest_prediction.analysis.level_review.to_level }}</h3>
                <p>{{ selected.latest_prediction.analysis.level_review.reason }}</p>
                <small>原文依据：“{{ selected.latest_prediction.analysis.level_review.evidence }}”</small>
              </section>
              <p v-if="selected.latest_prediction.analysis?.status === 'error'" class="message error">大模型调用失败，本条已退回规则提取：{{ selected.latest_prediction.analysis.error }}</p>

              <section class="fp-section">
                <h3>评分构成</h3>
                <div class="dims">
                  <div v-for="(label, key) in dimensions" :key="key" class="dim">
                    <span>{{ label }}</span><i :style="{ '--v': selected.latest_prediction.breakdown[key] }"></i><b>{{ selected.latest_prediction.breakdown[key].toFixed(2) }}</b>
                  </div>
                </div>
                <p class="fine">四项按权重加权；紧急工单保底 0.75，同厂家横向推送另有加成。</p>
                <ul class="reasons"><li v-for="reason in selected.latest_prediction.push_reasons" :key="reason">{{ reason }}</li></ul>
              </section>

              <section class="fp-section">
                <h3>提取标签</h3>
                <div class="tags"><span v-for="tag in selected.latest_prediction.tags" :key="`${tag.category}-${tag.code}`" :class="{ ai: tag.llm || tag.source === 'llm' }" :title="tag.llm || tag.source === 'llm' ? (tag.source === 'llm' ? '来源：大模型' : '来源：规则与大模型') : `来源：${tagSources[tag.source] || '规则与 TF-IDF'}`">{{ tag.name }}</span><span v-if="!selected.latest_prediction.tags.length" class="none">未提取到有效标签</span></div>
                <p v-if="selected.latest_prediction.analysis?.new_terms?.length" class="fine">词表外新词，待人工确认、不参与评分：{{ selected.latest_prediction.analysis.new_terms.map(t => t.term).join('、') }}</p>
              </section>

              <section class="fp-section">
                <h3>相似历史工单</h3>
                <ol v-if="selected.latest_prediction.similar?.length" class="similar">
                  <li v-for="s in selected.latest_prediction.similar" :key="s.event_id">
                    <button @click="openSimilar(s.event_id)" :disabled="!rows.some(r => r.order.event_id === s.event_id)">{{ s.title }}</button>
                    <span class="sim">{{ percent(s.similarity) }}</span>
                    <small v-if="s.human_outcome">你的审核：{{ s.human_outcome.latest.action === 'correct' ? `改为 ${Number(s.human_outcome.latest.corrected_score).toFixed(2)}` : '确认' }}<template v-if="s.human_outcome.latest?.comment">，{{ s.human_outcome.latest.comment }}</template></small>
                    <small v-else>你还没审核过这条</small>
                    <small v-if="s.others_outcome" class="others">其他岗位：{{ s.others_outcome.latest.action === 'correct' ? `改为 ${Number(s.others_outcome.latest.corrected_score).toFixed(2)}` : '确认' }}（仅供参考）</small>
                  </li>
                </ol>
                <p v-else class="fine">预测时没有找到足够相似的历史工单。</p>
              </section>

              <section class="fp-section">
                <h3>AI 解读</h3>
                <template v-if="explanations[selected.latest_prediction.prediction_id]?.status === 'ok'">
                  <p class="explain">{{ explanations[selected.latest_prediction.prediction_id].explanation }}</p>
                  <ul class="reasons"><li v-for="p in explanations[selected.latest_prediction.prediction_id].key_points" :key="p">{{ p }}</li></ul>
                  <p class="fine">由 {{ explanations[selected.latest_prediction.prediction_id].model }} 根据评分明细和相似工单生成，不改变分数。</p>
                </template>
                <p v-else-if="explanations[selected.latest_prediction.prediction_id]?.status === 'error'" class="message error">生成失败：{{ explanations[selected.latest_prediction.prediction_id].error }}</p>
                <button v-if="explanations[selected.latest_prediction.prediction_id]?.status !== 'ok'" @click="explain(selected)"
                        :disabled="!llm?.enabled || explanations[selected.latest_prediction.prediction_id]?.status === 'loading'">
                  {{ explanations[selected.latest_prediction.prediction_id]?.status === 'loading' ? '正在生成…' : '生成 AI 解读' }}
                </button>
                <p v-if="!llm?.enabled" class="fine">配置大模型后可用，见 README 的“接入大模型”。</p>
              </section>

              <section v-if="selected.latest_feedback" class="fp-block green">
                <h3>{{ statuses[selected.effective_result.review_status] }}，审核人 {{ selected.latest_feedback.reviewer }}</h3>
                <p>{{ selected.latest_feedback.comment || '确认原模型结果' }}</p>
                <small>{{ formatTime(selected.latest_feedback.created_at) }}</small>
              </section>

              <section class="fp-section">
                <h3>预测与反馈记录 <span class="fine">{{ selected.history.length }} 次预测</span></h3>
                <details v-for="(entry, index) in [...selected.history].reverse()" :key="entry.result.prediction_id" :open="index === 0" class="history-entry">
                  <summary>{{ formatTime(entry.result.predicted_at) }} <span>{{ formatScore(entry.result.score) }}</span></summary>
                  <div v-for="review in entry.feedback" :key="review.feedback_id" class="history-review">
                    <strong>{{ review.action === 'confirm' ? '确认原结果' : '人工修改' }}，{{ review.reviewer }}</strong>
                    <p v-if="review.action === 'correct'">修正分数：{{ review.corrected_score == null ? '沿用原值' : formatScore(review.corrected_score) }}，{{ review.corrected_push_type ? types[review.corrected_push_type] : '沿用原类型' }}</p>
                    <p>{{ review.comment || '无备注' }}</p><small>{{ formatTime(review.created_at) }}</small>
                  </div>
                  <p v-if="!entry.feedback.length" class="fine">尚无人工反馈</p>
                </details>
              </section>
            </template>
            <div v-else class="empty"><p>选择一条工单，查看评分依据和反馈历史。</p></div>
          </aside>
        </div>
      </template>

      <LearningView v-else :key="profile.role" :role="profile.role" :reviewer="reviewer" :llm="llm" @update:reviewer="reviewer = $event" @changed="load()" />

      <footer class="page-footer">本地演示，数据保存在 SQLite 中。模拟工单与画像均为虚构，匹配分不是概率。</footer>
    </main>

    <dialog ref="modal" @cancel="busy && $event.preventDefault()" aria-labelledby="dialog-title">
      <form @submit.prevent="save">
        <div class="modal-heading"><h2 id="dialog-title">{{ modalKind === 'create' ? '新建工单并预测' : modalKind === 'confirm' ? '人工确认' : '修改推送结果' }}</h2><button type="button" class="close" @click="modal.close()" :disabled="busy" aria-label="关闭弹窗">×</button></div>
        <template v-if="modalKind === 'create'">
          <p class="fine">使用当前{{ profile.role }}的画像（模拟基础兴趣加上行为数据）计算匹配分。</p>
          <label>工单标题<input v-model="form.title" required maxlength="500" placeholder="例如：汽轮机轴承振动异常" /></label>
          <label>工单正文<textarea v-model="form.content" maxlength="20000" rows="4" placeholder="填写设备、异常现象等原始信息"></textarea></label>
          <div class="form-grid"><label>等级<select v-model="form.level"><option>一般</option><option>重要</option><option>紧急</option><option>建议</option></select></label><label>机组<select v-model="form.unit"><option value="">未填写</option><option>#1</option><option>#2</option><option>#3</option><option>#4</option></select></label></div>
        </template>
        <template v-else>
          <p class="modal-order">{{ target?.title }}</p>
          <p v-if="modalKind === 'confirm'" class="fine">确认表示接受这次预测的原模型结果；此前的人工修正仍会保留在历史中。</p>
          <label>审核人<input v-model="reviewer" required maxlength="200" /></label>
          <div v-if="modalKind === 'correct'" class="form-grid"><label>修正匹配分（0–1）<input v-model="form.score" required type="number" min="0" max="1" step="0.0001" /></label><label>推送类型<select v-model="form.type"><option v-for="(label, value) in types" :key="value" :value="value">{{ label }}</option></select></label></div>
          <label>{{ modalKind === 'correct' ? '修改理由（必填）' : '确认备注（选填）' }}<textarea v-model="form.comment" :required="modalKind === 'correct'" maxlength="2000" rows="3"></textarea></label>
        </template>
        <p v-if="modalError" class="message error" role="alert">{{ modalError }}</p>
        <div class="modal-actions"><button type="button" @click="modal.close()" :disabled="busy">取消</button><button class="primary" type="submit" :disabled="busy">{{ busy ? '正在保存…' : modalKind === 'create' ? '保存并预测' : modalKind === 'confirm' ? '确认并保存' : '保存修改' }}</button></div>
      </form>
    </dialog>
  </div>
</template>
