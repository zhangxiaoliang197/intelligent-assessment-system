<template>
  <div class="skill-selector">
    <span class="label">技能：</span>
    <el-tooltip :content="disabledHint" placement="top" :disabled="!disabled || !disabledHint">
      <el-select
        v-model="choice"
        class="skill-select"
        size="small"
        :disabled="disabled"
        placeholder="选择技能"
      >
        <el-option label="自动匹配（按问题语义）" value="__auto__" />
        <el-option label="关闭技能（自由规划）" value="__off__" />
        <el-option
          v-for="item in skills"
          :key="item.id"
          :label="item.name"
          :value="item.id"
        >
          <span>{{ item.name }}</span>
          <span class="opt-category">{{ item.category || '技能' }}</span>
        </el-option>
      </el-select>
    </el-tooltip>

    <!-- 本轮实际套用结果：可解释（匹配方式 + 匹配度），未生效时如实提示 -->
    <el-tooltip v-if="appliedTag" :content="tooltip" placement="bottom">
      <el-tag size="small" :type="appliedTag.type" effect="plain" class="applied-tag">
        {{ appliedTag.text }}
      </el-tag>
    </el-tooltip>
  </div>
</template>

<script setup lang="ts">
// ── 技能（生成剧本）选择器 ──
// 取值三态：__auto__=按问题自动匹配；__off__=关闭技能走自由规划；其余为显式技能 id。
// 命中结果由后端写在本轮生成的 plan.skill 中，这里只做展示与切换。
// 空值兜底显示为"关闭技能"：与服务端默认策略（IPAGE_SKILL_DEFAULT_MODE，默认 off）一致，
// 避免出现"界面显示自动匹配、实际未套用"的表里不一。

import { computed } from 'vue'
import type { IpageMatchedSkill, IpageSkill } from '@/stores/interactive'

const props = defineProps<{
  /** 当前选择：__auto__ / __off__ / 技能 id */
  modelValue: string
  /** 技能目录（来自 /ipage/skills） */
  skills: IpageSkill[]
  /** 本轮实际套用的技能 */
  applied?: IpageMatchedSkill | null
  disabled?: boolean
  /** 禁用原因（如"服务端已禁用技能匹配"），仅在 disabled 时作为提示展示 */
  disabledHint?: string
}>()

const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()

const choice = computed({
  get: () => props.modelValue || '__off__',
  set: (value: string) => emit('update:modelValue', value),
})

const MATCH_LABEL: Record<string, string> = {
  auto: '自动匹配',
  manual: '手动指定',
  inherited: '继承上一版',
}

const appliedTag = computed(() => {
  const applied = props.applied
  if (!applied || !applied.id) return null
  if (!applied.applied) {
    return { text: '技能未生效', type: 'warning' as const }
  }
  const score = typeof applied.score === 'number' ? ` ${applied.score.toFixed(2)}` : ''
  return { text: `已套用：${applied.name}${score}`, type: 'success' as const }
})

const tooltip = computed(() => {
  const applied = props.applied
  if (!applied || !applied.id) return ''
  const lines = [
    `${MATCH_LABEL[applied.matchedBy] || '已套用'}｜${applied.reason || ''}`,
  ]
  if (applied.candidates?.length) {
    lines.push('候选：' + applied.candidates
      .map((c) => `${c.name}(${Number(c.score).toFixed(3)})`).join('、'))
  }
  if (applied.unresolvedNeeds?.length) {
    lines.push('部分技能需求未生效：' + applied.unresolvedNeeds.join('；'))
  }
  return lines.filter(Boolean).join(' ｜ ')
})
</script>

<style scoped>
.skill-selector { display: flex; align-items: center; gap: 8px; }
.label { font-size: 13px; color: var(--text-secondary); font-weight: 500; white-space: nowrap; }
.skill-select { width: 210px; }
.opt-category { float: right; margin-left: 12px; font-size: 12px; color: var(--text-muted); }
.applied-tag { cursor: help; }
</style>
