<script setup>
// 匹配分仪表条：0–1 刻度，0.4–0.6 灰区用斜纹标出，填充色随推送类型变化
const props = defineProps({
  score: { type: Number, required: true },
  type: { type: String, default: 'personal' },
  size: { type: String, default: 'row' },
  original: { type: Number, default: null },
})
const pct = v => `${Math.max(0, Math.min(1, v)) * 100}%`
</script>

<template>
  <div class="gauge" :class="[size, type]" role="meter" :aria-valuenow="score" aria-valuemin="0" aria-valuemax="1"
       :aria-label="`匹配分 ${score.toFixed(2)}`">
    <div class="gauge-track">
      <span class="gauge-gray" aria-hidden="true"></span>
      <span class="gauge-fill" :style="{ width: pct(score) }"></span>
      <span v-if="original !== null && original !== score" class="gauge-ghost" :style="{ left: pct(original) }"
            :title="`模型原始分 ${original.toFixed(4)}`"></span>
    </div>
    <div v-if="size === 'panel'" class="gauge-scale" aria-hidden="true">
      <span style="left:0">0</span><span style="left:40%">0.4</span><span style="left:60%">0.6</span><span style="left:100%">1</span>
    </div>
  </div>
</template>
