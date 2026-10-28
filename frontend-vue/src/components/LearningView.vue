<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  applyProfiles, applyWeights, fetchMetrics, fetchTerms, fetchVocabulary, fetchWeights,
  resetWeights, reviewTerm, runPushAll, suggestProfiles, suggestWeights,
} from '../api.js'

const props = defineProps({ reviewer: String, llm: Object, role: String })
const emit = defineEmits(['update:reviewer', 'changed'])
const reviewerName = computed({ get: () => props.reviewer, set: v => emit('update:reviewer', v) })

const dims = { device_type: '设备类型', behavior: '行为兴趣', role: '岗位职责', manufacturer: '厂家匹配' }
const buckets = { device_interests: '设备', fault_interests: '故障', keyword_interests: '关键词', mfr_interests: '厂家' }
const categories = { device_type: '设备类型', manufacturer: '厂家', fault_type: '故障类型', keyword: '技术关键词' }
const metrics = ref(null)
const weights = ref(null)
const weightSuggestion = ref(null)
const profileOut = ref(null)
const chosen = reactive({})
const terms = ref([])
const vocab = ref({})
const termCodes = reactive({})
const busy = ref('')
const error = ref('')
const notice = ref('')

const pct = v => v == null ? '—' : `${(v * 100).toFixed(1)}%`
const formatTime = v => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : ''
const pendingTerms = computed(() => terms.value.filter(t => t.status === 'pending'))
const decidedTerms = computed(() => terms.value.filter(t => t.status !== 'pending'))

async function run(name, fn) {
  busy.value = name
  error.value = ''
  notice.value = ''
  try { await fn() } catch (e) { error.value = e.message } finally { busy.value = '' }
}
async function refresh() {
  const [m, w, t, v] = await Promise.all([fetchMetrics(), fetchWeights(props.role), fetchTerms(), fetchVocabulary()])
  metrics.value = m
  weights.value = w
  terms.value = t
  vocab.value = v
}
const loadAll = () => run('load', refresh)
const pushAll = () => run('pushAll', async () => {
  const out = await runPushAll()
  notice.value = `已为 ${out.users.length} 个岗位重新评分：` + out.users.map(u => `${u.user_id} 变化 ${u.saved} 条`).join('，') + '。'
  await refresh()
  emit('changed')
})
const suggest = () => run('suggest', async () => { weightSuggestion.value = await suggestWeights(props.role) })
const apply = () => run('apply', async () => {
  weights.value = await applyWeights({ weights: weightSuggestion.value.suggested, reviewer: reviewerName.value, role: props.role,
    note: `MAE ${weightSuggestion.value.mae_current} → ${weightSuggestion.value.mae_suggested}，样本 ${weightSuggestion.value.samples}` })
  weightSuggestion.value = null
  notice.value = `${props.role}的专属权重已生效。点击“全部岗位重新推送”让已有工单按新权重重新评分。`
  emit('changed')
})
const reset = () => run('reset', async () => {
  weights.value = await resetWeights(reviewerName.value, props.role)
  notice.value = `${props.role}已改回使用全局权重。`
})
const loadProfiles = () => run('profiles', async () => {
  profileOut.value = await suggestProfiles()
  for (const k of Object.keys(chosen)) delete chosen[k]
  profileOut.value.suggestions.forEach((s, i) => { chosen[i] = true })
})
const applyChosen = () => run('applyProfiles', async () => {
  const items = profileOut.value.suggestions.filter((s, i) => chosen[i])
    .map(s => ({ user_id: s.user_id, bucket: s.bucket, code: s.code, suggested: s.suggested }))
  const out = await applyProfiles({ items, reviewer: reviewerName.value })
  notice.value = `已调整 ${out.changed.length} 项兴趣。画像会在下次读取时重新计算。`
  profileOut.value = null
  emit('changed')
})
const decide = (t, status) => run(`term-${t.term}`, async () => {
  const code = termCodes[`${t.term}|${t.category}`]
  terms.value = await reviewTerm(t.term, { category: t.category, status, reviewer: reviewerName.value, code: status === 'accepted' ? code : null })
  vocab.value = await fetchVocabulary()
  notice.value = status === 'accepted' ? `“${t.term}”已加入词典，映射到 ${code.toUpperCase()}。` : status === 'rejected' ? `已忽略“${t.term}”。` : `“${t.term}”已移回待审核。`
})
onMounted(loadAll)
</script>

<template>
  <div class="learn">
    <div class="learn-bar">
      <label>审核人<input v-model="reviewerName" maxlength="200" aria-label="审核人" /></label>
      <div class="row-buttons tight"><button @click="pushAll" :disabled="!!busy">{{ busy === 'pushAll' ? '正在重新评分…' : '全部岗位重新推送' }}</button><button class="text-button" @click="loadAll" :disabled="!!busy">刷新数据</button></div>
    </div>
    <div v-if="error" class="message error" role="alert">{{ error }}</div>
    <div v-if="notice" class="message success" role="status">{{ notice }}</div>

    <section class="learn-section" aria-labelledby="m-title">
      <header><h2 id="m-title">模型与人工判断的一致程度</h2><p>只统计已经人工确认或修改过的推送。确认视为认可模型分数，修改以修正值为准。</p></header>
      <div v-if="metrics && metrics.reviewed" class="readouts">
        <div><strong>{{ metrics.reviewed }}</strong><span>已审核推送</span></div>
        <div><strong>{{ pct(metrics.confirm_rate) }}</strong><span>直接确认</span></div>
        <div><strong>{{ metrics.mae.toFixed(3) }}</strong><span>平均分差</span></div>
        <div><strong>{{ pct(metrics.push_decision_agreement) }}</strong><span>推送判断一致（阈值 {{ metrics.push_threshold }}）</span></div>
        <div><strong>{{ pct(metrics.triage_recall) }}</strong><span>被修改的推送中，事先标为重点审核的比例</span></div>
      </div>
      <p v-if="metrics?.before_after?.compared" class="verdict">调整之后，同一批 {{ metrics.before_after.compared }} 条被审核工单重新预测：平均分差 {{ metrics.before_after.mae_before.toFixed(3) }} → {{ metrics.before_after.mae_after.toFixed(3) }}，推送判断一致 {{ pct(metrics.before_after.agreement_before) }} → {{ pct(metrics.before_after.agreement_after) }}。</p>
      <p v-else-if="metrics?.reviewed" class="fine ba-hint">{{ metrics.before_after?.note }}</p>
      <p v-else class="empty-line">还没有人工审核记录。在工作台确认或修改几条推送后，这里会显示模型与人工判断的差距。</p>
    </section>

    <section class="learn-section" aria-labelledby="w-title">
      <header><h2 id="w-title">{{ role }}的四维评分权重</h2><p>每个岗位可以有自己的权重；没有单独设置时使用全局权重。系统用该岗位的人工审核结果反推一组更贴近人工判断的权重，只给建议，你批准后才生效。</p></header>
      <div v-if="weights" class="weights">
        <div class="weights-head"><span>当前生效：{{ weights.source === 'role' ? '本岗位专属权重' : weights.source === 'learned' ? '全局权重（经人工批准的学习结果）' : '默认权重' }}</span><span v-if="weights.updated_at">{{ formatTime(weights.updated_at) }}</span></div>
        <div v-for="(label, key) in dims" :key="key" class="weight-row">
          <span>{{ label }}</span>
          <div class="pair">
            <i class="now" :style="{ '--v': weights.weights[key] }"></i>
            <i v-if="weightSuggestion?.status === 'ok'" class="next" :style="{ '--v': weightSuggestion.suggested[key] }"></i>
          </div>
          <b>{{ weights.weights[key].toFixed(2) }}<template v-if="weightSuggestion?.status === 'ok'"> 改为 {{ weightSuggestion.suggested[key].toFixed(2) }}</template></b>
        </div>
      </div>
      <p v-if="weightSuggestion?.status === 'insufficient'" class="empty-line">本岗位至少需要 {{ weightSuggestion.required }} 条非紧急工单的审核记录，目前只有 {{ weightSuggestion.samples }} 条。</p>
      <p v-if="weightSuggestion?.status === 'ok'" class="verdict">基于 {{ weightSuggestion.samples }} 条审核记录：平均分差从 {{ weightSuggestion.mae_current }} 降到 {{ weightSuggestion.mae_suggested }}。{{ weightSuggestion.note }}</p>
      <div class="row-buttons">
        <button @click="suggest" :disabled="!!busy">{{ busy === 'suggest' ? '正在计算…' : '根据审核结果计算建议权重' }}</button>
        <button v-if="weightSuggestion?.status === 'ok'" class="primary" @click="apply" :disabled="!!busy || !reviewerName">应用为本岗位权重</button>
        <button v-if="weights?.source === 'role'" class="text-button" @click="reset" :disabled="!!busy">改回使用全局权重</button>
      </div>
    </section>

    <section class="learn-section" aria-labelledby="p-title">
      <header><h2 id="p-title">画像调整建议</h2><p>某类工单被反复人工下调或上调时，建议相应降低或提高用户对该标签的兴趣。每条建议都附带依据。</p></header>
      <div class="row-buttons"><button @click="loadProfiles" :disabled="!!busy">{{ busy === 'profiles' ? '正在分析…' : '分析人工修改记录' }}</button></div>
      <template v-if="profileOut">
        <div v-if="profileOut.review?.status === 'ok'" class="ai-summary">
          <h3>AI 复盘</h3>
          <p>{{ profileOut.review.summary }}</p>
          <ul><li v-for="p in profileOut.review.patterns" :key="p.pattern">{{ p.pattern }}<small>（{{ p.feedback_ids.length }} 条修改）</small></li></ul>
        </div>
        <p v-if="!profileOut.suggestions.length" class="empty-line">{{ profileOut.corrections ? `已分析 ${profileOut.corrections} 条人工修改，没有同一标签被反复修改的情况。` : '还没有人工修改记录。' }}</p>
        <ul v-else class="suggestions">
          <li v-for="(s, i) in profileOut.suggestions" :key="`${s.user_id}-${s.code}`">
            <label class="check"><input type="checkbox" v-model="chosen[i]" />
              <span><b>{{ s.user_id }}</b> 的{{ buckets[s.bucket] }}兴趣 {{ s.name }}（{{ s.code }}）：{{ s.current.toFixed(2) }} {{ s.direction === 'down' ? '降为' : '升为' }} {{ s.suggested.toFixed(2) }}</span>
            </label>
            <span class="tag-ai" v-if="profileOut.review?.supported_suggestions?.includes(i)">修改理由支持</span>
            <details><summary>{{ s.evidence_count }} 条依据</summary>
              <p v-for="e in s.evidence" :key="e.prediction_id">{{ e.title }}：模型 {{ e.model_score.toFixed(2) }}，人工 {{ e.corrected_score.toFixed(2) }}。{{ e.comment }}</p>
            </details>
          </li>
        </ul>
        <div v-if="profileOut.suggestions.length" class="row-buttons"><button class="primary" @click="applyChosen" :disabled="!!busy || !reviewerName || !Object.values(chosen).some(Boolean)">应用选中的调整</button></div>
      </template>
    </section>

    <section class="learn-section" aria-labelledby="t-title">
      <header><h2 id="t-title">词表外新词</h2><p>大模型在工单中发现、但词典还没有的词。接受后会映射到一个标签代码，立即参与规则提取。</p></header>
      <p v-if="!terms.length" class="empty-line">{{ llm?.enabled ? '还没有发现新词。' : '启用大模型并导入工单后，这里会列出它发现的新词。' }}</p>
      <table v-else class="terms">
        <thead><tr><th>新词</th><th>类别</th><th>出现工单</th><th>映射到标签代码</th><th><span class="sr-only">操作</span></th></tr></thead>
        <tbody>
          <tr v-for="t in pendingTerms" :key="`${t.term}|${t.category}`">
            <td><b>{{ t.term }}</b><small>{{ t.example_span }}</small></td>
            <td>{{ categories[t.category] }}</td>
            <td>{{ t.hits }}</td>
            <td><input v-model="termCodes[`${t.term}|${t.category}`]" :list="`codes-${t.category}`" placeholder="选已有代码或输入新代码" :aria-label="`${t.term} 的标签代码`" />
              <datalist :id="`codes-${t.category}`"><option v-for="(words, code) in vocab[t.category]" :key="code" :value="code">{{ words.join('/') }}</option></datalist></td>
            <td class="term-actions"><button @click="decide(t, 'accepted')" :disabled="!!busy || !termCodes[`${t.term}|${t.category}`] || !reviewerName">接受</button><button class="text-button" @click="decide(t, 'rejected')" :disabled="!!busy || !reviewerName">忽略</button></td>
          </tr>
          <tr v-for="t in decidedTerms" :key="`${t.term}|${t.category}`" class="decided">
            <td><b>{{ t.term }}</b></td><td>{{ categories[t.category] }}</td><td>{{ t.hits }}</td>
            <td>{{ t.status === 'accepted' ? '已加入词典' : '已忽略' }}</td>
            <td><button class="text-button" @click="decide(t, 'pending')" :disabled="!!busy">撤销</button></td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
