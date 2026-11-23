<template>
  <div class="followup-answer">
    <p class="fa-intro">{{ intro }}</p>

    <!-- 数据溯源结果 -->
    <template v-if="mode === 'trace'">
      <div class="fa-metric-card">
        <div class="fa-metric-head">
          <span class="fa-metric-name">{{ detail.metric?.name || '指标' }}</span>
          <span class="fa-metric-value">
            {{ detail.metric?.value }}<small v-if="detail.metric?.unit"> {{ detail.metric.unit }}</small>
          </span>
        </div>
        <div v-if="detail.metric?.formula" class="fa-formula">
          <span class="fa-formula-label">计算口径</span>
          <code>{{ detail.metric.formula }}</code>
        </div>
        <div v-if="detail.metric?.tableName" class="fa-source">
          数据来源：MySQL · assessment.{{ detail.metric.tableName }}
        </div>
      </div>

      <div class="fa-section-title">溯源链路</div>
      <el-timeline class="fa-timeline">
        <el-timeline-item
          v-for="(step, idx) in detail.steps || []"
          :key="idx"
          :type="step.level === '指标属性' ? 'primary' : step.level === '数据绑定' ? 'success' : 'info'"
        >
          <div class="fa-step">
            <span class="fa-step-level">{{ step.level }}</span>
            <span class="fa-step-title">{{ step.title }}</span>
            <div v-if="step.detail" class="fa-step-detail">{{ step.detail }}</div>
          </div>
        </el-timeline-item>
      </el-timeline>
    </template>

    <!-- 归因分析结果 -->
    <template v-else>
      <div class="fa-level-card">
        <div class="fa-level-item">
          <span>红方指数</span>
          <strong>{{ detail.result?.redIndex }}</strong>
        </div>
        <div class="fa-level-item">
          <span>蓝方指数</span>
          <strong>{{ detail.result?.blueIndex }}</strong>
        </div>
        <div class="fa-level-item">
          <span>净差</span>
          <strong>{{ detail.result?.delta ?? '-' }} 分</strong>
        </div>
      </div>

      <div class="fa-section-title">具体推理过程</div>
      <div class="fa-reasoning">
        <div v-for="item in detail.reasoningSteps || []" :key="item.step" class="fa-reasoning-step">
          <span class="fa-reasoning-index">{{ item.step }}</span>
          <div class="fa-reasoning-body">
            <div class="fa-reasoning-name">{{ item.title }}</div>
            <div class="fa-reasoning-detail">{{ item.detail }}</div>
          </div>
        </div>
      </div>

      <div class="fa-section-title">主要归因</div>
      <div class="fa-cause-list">
        <div v-for="cause in (detail.causes || []).slice(0, 5)" :key="cause.id" class="fa-cause">
          <div class="fa-cause-head">
            <el-tag
              size="small"
              :type="cause.level === '高' ? 'danger' : cause.level === '中' ? 'warning' : 'info'"
              effect="plain"
            >{{ cause.kind }}</el-tag>
            <span class="fa-cause-title">{{ cause.title }}</span>
            <span v-if="cause.impact" class="fa-cause-impact">±{{ cause.impact }} {{ cause.impactUnit }}</span>
          </div>
          <div class="fa-cause-detail">{{ cause.detail }}</div>
        </div>
      </div>
    </template>

    <div class="fa-footer">
      <el-button size="small" type="primary" :icon="TopRight" @click="$emit('jump')">
        {{ mode === 'trace' ? '在动态本体中查看高亮' : '在动态本体中查看推理过程' }}
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { TopRight } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{
  mode: 'trace' | 'attribution'
  detail: any
}>(), {
  detail: () => ({})
})

defineEmits<{ (e: 'jump'): void }>()

// 对话式开头，先说结论，再给结构化明细
const intro = computed(() => {
  if (props.mode === 'trace') {
    const metric = props.detail?.metric || {}
    const value = metric.value !== undefined ? `${metric.value}${metric.unit || ''}` : ''
    return `已为你完成「${metric.name || '该指标'}」的结果溯源：本次取值为 ${value}，下面是从本体指标属性到原始数据表的完整链路。`
  }
  return `已基于动态本体完成归因分析：${props.detail?.summary || ''}`
})
</script>

<style scoped>
.followup-answer {
  min-width: 0;
  max-width: 100%;
  margin-top: 4px;
}

.fa-intro {
  margin: 0 0 12px;
  font-size: 1.05rem;
  line-height: 1.8;
  color: var(--text-primary);
}

.fa-metric-card,
.fa-level-card {
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.fa-metric-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.fa-metric-name {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
}

.fa-metric-value {
  font-size: 18px;
  font-weight: 700;
  color: #1d4ed8;
}

.fa-metric-value small {
  font-size: 12px;
  font-weight: 500;
  color: #4b5563;
}

.fa-formula {
  margin-top: 8px;
  padding: 8px 10px;
  background: #fff;
  border-radius: 8px;
  font-size: 12px;
}

.fa-formula-label {
  color: #6b7280;
  margin-right: 8px;
}

.fa-formula code {
  color: #374151;
  word-break: break-all;
}

.fa-source {
  margin-top: 8px;
  font-size: 12px;
  color: #6b7280;
}

.fa-level-card {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
}

.fa-level-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #6b7280;
}

.fa-level-item strong {
  font-size: 18px;
  color: #1d4ed8;
}

.fa-section-title {
  margin: 14px 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.fa-timeline {
  padding-left: 2px;
}

.fa-step-level {
  display: inline-block;
  margin-right: 8px;
  padding: 0 6px;
  border-radius: 4px;
  background: #eef2ff;
  color: #4f46e5;
  font-size: 11px;
}

.fa-step-title {
  font-size: 12px;
  font-weight: 600;
  color: #111827;
  word-break: break-all;
}

.fa-step-detail {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.6;
  word-break: break-all;
}

.fa-reasoning-step {
  display: flex;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px dashed #e5e7eb;
}

.fa-reasoning-step:last-child {
  border-bottom: none;
}

.fa-reasoning-index {
  flex: 0 0 20px;
  height: 20px;
  border-radius: 50%;
  background: #3b82f6;
  color: #fff;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.fa-reasoning-body {
  min-width: 0;
}

.fa-reasoning-name {
  font-size: 12px;
  font-weight: 600;
  color: #111827;
}

.fa-reasoning-detail {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.6;
  color: #4b5563;
  word-break: break-all;
}

.fa-cause {
  padding: 8px 0;
  border-bottom: 1px dashed #e5e7eb;
}

.fa-cause:last-child {
  border-bottom: none;
}

.fa-cause-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.fa-cause-title {
  font-size: 12px;
  font-weight: 600;
  color: #111827;
}

.fa-cause-impact {
  font-size: 11px;
  color: #dc2626;
}

.fa-cause-detail {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: #6b7280;
  word-break: break-all;
}

.fa-footer {
  margin-top: 12px;
}
</style>
